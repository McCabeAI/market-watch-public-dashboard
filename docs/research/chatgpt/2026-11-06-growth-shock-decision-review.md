# ChatGPT PM growth-shock decision review — 6 November 2026

Research judgment on the frozen packet. Not an order, and not a book, ledger, or hypothesis update.

**Question.** Is the AI/credit selloff creating a sustained growth trade, or an opportunity to fade an overreaction?

**Answer.** Neither add. The 5 November equity drop is real, oil rebounded in the same session, and the US front end had already been rallying for weeks. That mix does not identify a growth trade to add, and it does not identify a clean overreaction to fade. Cut the owned CORRA 2027 receive to the size the adverse path and the loss budget buy. Hold the owned EURUSD long at USD 5 million. Leave AUDJPY, AUDNZD, and SOFR flat.

| Expression | Preferred action | Size | Adverse path | P&L on that path | Loss budget |
| --- | --- | --- | ---: | ---: | ---: |
| CORRA 2027 H/M/U/Z receive | Cut | USD 47,904,192 | average 3.26 | −100,000 | 100,000 |
| EURUSD long | Hold | USD 5,000,000 | 1.113 | −41,875 | 45,000 |
| AUDJPY short | No trade | 0 | sample high, illustration only | 0 | 0 |
| AUDNZD short | No trade | 0 | sample high, illustration only | 0 | 0 |
| SR3H7 March 2027 | Wait | 0 | declined receive 4.53, declined pay 3.94 | 0 | 0 |

P&L is signed from the frozen reference. Positive would be a gain. Targets, yardsticks, and payoff ratios are not probabilities and not expected values. Financing is stated beside the paths and is not subtracted into an edge.

Clocks stay separate. The freeze and the news cutoff are 2026-11-06T06:25:49.281876-05:00. Score inputs were ingested at 2026-11-06T11:25:49Z. Market state was generated at 2026-11-06T11:42:41Z. A field is not treated as known at the freeze label merely because the file carries that label. This note uses no market information after the frozen artifact. The scheduled-output delivery commit `f0cadc27229365e20ad9484fbb1eb8409de794d3` is not in this clone. The blob `6bec37cfa0e24e4e638d58a1b7aaf779d76339f8` on this branch is what was checked, and its embedded base-packet hash matches.

Support, including the source map, the three judgments, the calculator, and the independent verification, is under `docs/research/chatgpt/2026-11-06-growth-shock-decision/`. The verifier recomputed units, signs, sample lengths, and lineage and exited clean. The arithmetic below is that checked arithmetic.

## 1. Current book

The book is the ChatGPT seat at input commit `680297f3898081789794d20b765a5c908b6b93fe`. The same two positions are in the snapshot's prior book. The canonical book on this branch's HEAD is a later blob and was not used.

**CORRA 2027 H/M/U/Z receive**, `pm-chatgpt-595561a1b90f`. Long, USD 100,000,000, entry 3.40 at 2026-09-20T02:06:32Z, book mark 3.10875 at 2026-11-05T11:31:47Z, stored unrealized USD 291,250, risk capital and funding draw USD 1,000,000. The move from 3.40 to 3.10875 is 29.125 bp. The identity 29.125 × 10,000 = 291,250 is the book's own risk field: USD 10,000 per bp at USD 100 million, on a parallel move of the equal-weight average. That identity is four times the single quarterly-contract convention of USD 25 per bp per USD 1 million. The single-contract convention is used later for SR3 and is not used to rewrite this book.

The frozen legs, observation dates null, are CRAH27 2.885, CRAM27 3.01, CRAU27 3.11, and CRAZ27 3.20. The equal-weight average is 3.05125. Versus the book mark that is −5.75 bp of rate, which is USD +57,500 for the receive at USD 100 million. That mark is noncanonical. It is not the stored unrealized P&L, and it has no observation time.

**EURUSD long**, `pm-chatgpt-aef5bacd43d3`. USD 5,000,000, entry 1.1267 dated 2026-11-04, book mark still 1.1267, stored unrealized 0, risk capital and funding draw USD 50,000, opened 2026-11-05T08:52:26.537704-05:00. The frozen spot is 1.1224 on 2026-11-05. Paper P&L on a USD notional is 5,000,000 × (1.1224 / 1.1267 − 1) = −19,082 to the nearest dollar. That is not an exchange-lot count, and it is not the book's stored zero.

Seat funding already on the book is USD 25,105.56 at 3.97 percent ACT/360 on a funded draw of USD 1,050,000. Realized P&L of 1,036,875 and total P&L of 1,328,125 are history. They are not a reason to keep the risk. The last action was HOLD. Both positions are judged from flat at the frozen references.

Combined noncanonical gross, before financing, is +57,500 − 19,082 = +38,418. The prompt's figure matches to the nearest dollar. It is a research mark, not an edge, and the stock funding charge is not netted against it.

## 2. Whole market

On 2026-11-05 the Nasdaq log return was −5.68 percent, to 24315, which is the low of its 126 observations. The Dow log return was −3.50 percent. The Russell log return was −4.55 percent. The same session WTI rose from 88.12 to 90.52 and Brent from 94.62 to 98.29. The oil series notes say the futures history includes contract rolls, so roll jumps are not clean economic returns. Copper fell. Growth stress and an oil rebound are both in the closes. One session does not name a single cause.

The US two-year ended at 446 bp, 4.46 percent, down 12 bp. Eight of the 125 daily differences in the 126-point history are at least 12 bp in absolute size, so the day is a tail day inside a rally that was already underway: from 6 October the two-year is down 33 bp and the ten-year, at 484 bp, is down 43 bp from the same date and down 6 bp on the day. Twos-tens steepened 6 bp to 38 bp. The ten-year breakeven ended at 224 bp, down about 2 bp, so the nominal rally is not a breakeven collapse. The real ten-year stops on 4 November at 264 bp and cannot split the 5 November move.

S&P 7688.62 and VIX 16.61 are 4 November, when the S&P log return was positive and VIX fell. They are not a calm reading of 5 November and they are not a stress reading of it. High-yield OAS at 332 bp is also 4 November. The AI credit stress in the packet is news from 5 and 6 November: SoftBank shares and default insurance, Asian dollar bonds, a data-center loan headline. It is not a high-yield break in the series on hand. Broad USD ends 30 October at 121.6656, near the top of its own 126 observations, and does not include November.

Canada's two-year, the CORRA proxy, ended 4 November at 322 bp, down 4 bp that day and 19 bp below the 28 October close of 341 bp. It was not observed on the US rally day. There is no CORRA strip history. The usable path is the futures strip itself. Benchmark CORRA is 2.52 on 4 November. The owned quarters sit 36.5, 49, 59, and 68 bp over that benchmark. The curve is still higher further out: CRAZ28 is 3.40. That is a priced quarterly path. It is not a hike count and not a fair value.

Meeting-price levels are excluded. Kevin's warning that the derived front Fed meeting estimate is about 8 bp wrong was applied by dropping every supplied derived meeting-price estimate, not by repairing it. Calendars remain. The next Bank of Canada date in the calendar is 9 December 2026, and 27 January 2027 sits at the far end of an 8 to 12 week horizon. The next US dates inside that horizon are 9 December 2026 and 27 January 2027. No step in basis points is inferred from a date.

Temperature scores are scores, with an anchor at 50, not raw prints and not a consensus. Canada's activity score is near the anchor and its impulse is warming. Canada's inflation score is neutral, with a warm headline leg and an underlying leg near the anchor. Canada's labor components are `source_failed` and unavailable, so the labor score is not an employment print. The US labor score for September 2026 is 51.26, impulse −1.54, near the anchor and mildly cooling. US payrolls, unemployment, and wages are that September current release. Chicago Fed labor rows and claims rows exist later in the calendar and do not carry numeric levels in the component records used here. There is no October or November employment-situation print and no consensus. US core PCE is the retained July release and the source failed. The inflation score that matches that staleness is warm and static. Headlines say jobs data and inflation data are ahead. A headline is not a print.

Euro-area yields are labeled 6 November, at 295 bp, 303 bp, and 322 bp for the two-year, five-year, and ten-year, and are not backdated onto 5 November. The 5 November Government and Bank of Canada statement renews the inflation objective. It is not a 2027 path. A 2.75 neutral proxy is not a Bank of Canada forecast. The earlier central shape 2.90 / 2.98 / 3.05 / 3.10 was not fair value and is not restored.

## 3. How the owned trades sit in that market

The receive's accounting mark, 3.10875, cannot be lined up in time with the frozen strip. Against the proxy that has a date, Canada's two-year had already fallen 19 bp from the 28 October high by 4 November, and it has no 5 November print. The front contract, 2.885, is the compressed leg. The back, 3.11 and 3.20, is where the premium over the 2.52 benchmark still lives. The position has not been marked, in a way this packet can time, as a 5 November growth trade. The noncanonical +57,500 is the gap from the book mark to the frozen average. It is giveback already in the research mark, and it is not a reason to keep USD 100 million.

The euro long exists because the PM overrode the 5 November research rejection: the broad-dollar thesis was accepted without an EUR-specific residual. The override is a fact about the book. This packet does not supply the residual after the fact. Around the open, EURUSD was 1.1179 on 3 November, 1.1267 on 4 November, and 1.1224 on 5 November. The 5 November log change is about −0.38 percent, inside a daily standard deviation of 0.31 percent log. Oil bounced inside a history whose daily standard deviation is about 3.2 percent log for WTI, with the roll caveat, and it did not return to the 30 October closes of 104.12 and 117.64. USDCAD firmed slightly on 5 November. The dollar was not uniformly offered on the equity-down day. The long is about 0.38 percent underwater versus the series and flat on the book.

The two positions can share a growth scare and still disagree on oil. Cheaper energy helps an importer long and challenges a Canadian receiver. The 5 November tape pushed those channels by ordinary amounts in opposite directions. Each size is judged on its own path.

## 4. Alternatives

### CORRA: hold USD 100 million, cut, or close

The adverse path is chosen first. It is an equal-weight average of 3.26, which is 20.875 bp above 3.05125. Canada's two-year decline from 341 bp on 28 October to 322 bp on 4 November is 19 bp. A reversal of that decline, as a proxy illustration and not as a hedge ratio, would lift the frozen average by about 19 bp. The extra distance to 3.26 keeps the adverse from being forced to equal the two-year. The old review price 3.26375 is not inherited. Measured from the frozen average it is a different trade from the one written off the book mark 3.10875. The old trading target 3.03375 is 1.75 bp under the frozen average, inside a single ordinary CA_2Y day, and it is not a remaining target. Gap stress, if the exit is jumped, is 3.40, which is both the original entry and CRAZ28.

The judgmental range over 8 to 12 weeks is 2.98 to 3.02 on the average. It is judgment, not fair value. It is built by leaving the March and June contracts near the frozen 2.885 and 3.01 and allowing September and December to compress. From 3.05125 the nearer edge is 3.125 bp and the further edge is 7.125 bp. The curve's rise into 2028 means this is a trading compression, not a claim about the eventual policy rate.

The loss budget on that idea is USD 100,000. It is not raised to keep USD 100 million. At the book identity, the 20.875 bp adverse on USD 100 million is USD 208,750. On a round USD 50 million it is USD 104,375, which is USD 4,375 over the budget. Dividing the budget by the loss per unit buys USD 47,904,192. That is the size. A practical round to USD 48 million would change the adverse loss by a few hundred dollars. The figure used here is the unrounded budget size.

At that size the nearer target, 3.02, pays about USD 14,970 and the further target, 2.98, pays about USD 34,132. The planned exit is the adverse level itself, so the planned-exit loss is the USD 100,000 budget. Gap stress to 3.40 is about USD −167,066. The CA_2Y proxy's full-sample daily standard deviation is 4.99 bp, and the same standard deviation scaled by the square root of 40 trading days is 31.6 bp. The 20.875 bp adverse sits inside that 40-day proxy scale. The scale is a convention, not a probability, and the proxy is not a CORRA strip.

From flat at 3.05125 the receive still has a sign. The back of the strip prices 59 and 68 bp over a 2.52 benchmark, the activity score is neutral, the underlying inflation score is near the anchor, and 9 December is a real calendar date inside the horizon. Closing gives up the 3 to 7 bp range. Holding USD 100 million spends more than the budget on the adverse path. The cut is the from-flat size. It happens to land near the old harvest-to-50m idea, and it does not wait for 3.03375 to print.

Forward financing uses the SOFR fixing of 3.94 percent, observed 4 November, ACT/360, 70 calendar days, on the risk-capital draw rather than the full notional. The book's shock capital is USD 1,000,000 on USD 100 million, which is 100 bp on the book identity. Scaled to the sized notional the draw is about USD 479,042, and the charge is about USD 3,670. The quant file also prices the round-50m card's USD 500,000 draw at USD 3,830.56. Neither charge decides the cut. The stock charge of USD 25,105.56 is already accrued and is not a forward edge.

Room leads are submitted actions, not fills, and not a crowding measure. Positioning-cynic wants a smaller March CORRA short because 2.885 versus cash at 2.52 no longer looks special. The front is the compressed leg. Their short is not this book, and cutting it is not a reason to drop the strip receive. The pragmatist wants to harvest an oversized March receive and keep a smaller receive while premium over 2.52 remains. The shape point is the same one used here. The premium over cash is not a count of unused hikes, and this cut is on the four-leg average rather than a March-only position.

### EURUSD: hold, reduce, exit, or add

The adverse path is the sample low, 1.113 on 29 October. Nothing below that low is invented. The daily-close review at 1.1179 is retested and kept as a review. From 1.1224 it is 0.0045, about 0.40 percent, and 21 of 125 absolute daily changes were at least that large, counting the 16 October move of exactly 0.0045. Treating 1.1179 as the budgeted failure would treat ordinary noise as the failure of the idea. The loss budget to sit through 1.113 is USD 45,000. At USD 5 million the paper loss is USD −41,875, inside the budget. The planned-exit loss at 1.1179 is USD −20,046. Gap stress is the same 1.113 path, USD −41,875.

The near reference 1.1356 stays the prior arithmetic marker. It is not rolled forward onto 1.1224. At USD 5 million it pays about USD 58,803 from the frozen spot. The far reference is 1.1467, the median of the 126 closes, and it pays about USD 108,250. Neither number is fair value. The own-history daily standard deviation is 0.31 percent log, and the 40-trading-day scale of that standard deviation is 1.96 percent log. The adverse move is inside that scale.

From flat at 1.1224 the USD 5 million long stays. The 5 November giveback and the oil rebound are ordinary relative to the embedded histories, the 30 October oil levels have not printed, and the broad-dollar interpretation is why the position exists. Adding to USD 10 million takes the 1.113 path to about USD −83,749, which is outside the budget, and no euro residual has appeared to justify the add. The budget would arithmetically allow about USD 5.37 million. That leftover budget is not spent. Cutting to USD 2.5 million is the same idea at a size the adverse path does not require. Exiting realizes the noncanonical −19,082 versus entry, which the book has not marked, and gives up the path toward 1.1356 and 1.1467 after two sessions.

The funding draw kept is USD 50,000, about USD 383 over 70 days at 3.94 percent. Executable forward points are absent. A sovereign sensitivity, not a forward and not a spot forecast, is 5,000,000 × ((4.46 − 2.95) / 100) × 70 / 360 = USD 14,680.56, using the US two-year on 5 November and the euro-area two-year labeled 6 November. The dates do not match. The yields are not deposit rates. The positive gap is a cost sensitivity of the long. It is smaller than the adverse budget and it does not decide the hold.

### AUDJPY short versus AUDNZD short

Neither short is a practical expression of a sustained growth shock, and neither is a practical fade of an overreaction. Both loss budgets are zero.

AUDJPY finished 5 November at 110.9275, a log decline of 0.078 percent, on the day Nasdaq made its sample low. The legs add up: AUDUSD's log move was −0.208 percent and USDJPY's was +0.130 percent. The yen weakened. Across the window the cross's decline is the Australian-dollar leg, not a yen bid. Inside the 126 observations the print sits in the lower part of the window. The sample low is 109.175 on 15 October. The sample high, and the adverse illustration, is 114.886 on 28 August. Paper loss of a USD 5 million short to that high is about USD 178,429. The one-year screen is the middle of the range. The five-year percentile and z are screens this 126-day file cannot rebuild. Descriptive correlations with Nasdaq and with WTI over the overlapping returns are near zero. Selling the cross here is a forecast that a beta which has not shown up in this sample will show up later.

The countercase is in the packet on its own. SoftBank shares and the cost of insuring its debt, Asian dollar bonds, and a data-center loan headline put Japan inside the AI-credit complex. A short AUDJPY is long the yen. Further yen weakness from a Japan-resident credit shock raises the cross. Oil agrees. Japan pays the import bill, and the 5 November rebound is in the direction that hurts the short. Australia's warmer inflation score and cooler labor score are September scores. They are not a completed repricing signal for a cross that ignored a 5.7 percent log equity drop. The next BoJ date is 18 December 2026 and the calendar status is unavailable, with no price. The next RBA date is 8 December 2026, with no price.

AUDNZD finished at 1.2453, a small log rise on the shock day, because the kiwi fell more than the Australian dollar. The five-year screen is the 99th percentile and a z near 2.75. The 126-day history cannot rebuild that screen, and a historical extreme is not proof of mispricing. Inside the sample, 119 of 126 observations are at or below the last print, and the high is 1.2529 on 28 October. That day was a NZDUSD drop of about 1.58 percent log with AUDUSD unchanged. NZDUSD's cheap screen is the same ratio from the other side. It is not independent proof. Paper loss of a USD 5 million short to the sample high is about USD 30,385.

The domestic scores that exist do not identify an Australian overreaction. New Zealand's activity impulse is softer and its labor score is cooler, which can justify a higher AUDNZD, and those New Zealand inflation and labor rows are `calendar_unparsed` with the previous release retained at 2026-Q2. AU-NZ and NZ-US yield histories are empty. The relationship of AUDNZD on the AU-NZ two-year is insufficient. There is no rates-spread fair value. The cross's correlation with Nasdaq in this sample is about zero, so it did not hedge the equity drop. Kevin's earlier AUDNZD example was coaching. It is not an instruction.

The room leads that open AUDNZD shorts of USD 5 million or USD 10 million are submitted actions, not fills. They fade a five-year extreme and a cheap kiwi. The cheap kiwi is the cross. Meeting-price language in those rationales is quarantined. An unmeasurable New Zealand cash carry is a reason the value case is incomplete.

### SOFR: receive, pay, or wait

Wait. The contract worth pricing, and the contract left unopened, is SR3H7, March 2027, implied rate 4.24 and price 95.76 on 5 November. Price equals 100 minus the rate. Over 8 to 12 weeks the contract is still a forward quarterly period. It can reprice as the 9 December and 27 January calendar dates approach. It is not a hike count.

SR3Z6, December 2026, at 4.115, is declined. It is one quarterly period. Holding it for 8 to 12 weeks runs through its expiry label. The two-year at 4.46 percent is a coupon yield. There is no SR3 history, so the coupon's −12 bp day is not a measured move in December SOFR. The front December contract is not a two-year substitute. The 17.5 bp gap from 4.115 to the 3.94 overnight fixing is a difference between a quarterly period and an overnight rate.

SR3H7 at 4.24 against the SOFR fixing of 3.94 percent, observed 4 November, is a 30 bp gap. The fixing is an overnight rate. The gap is not cheapness, not carry to be earned, and not a count of hikes. Later 2027 contracts would pull in later decision dates whose meeting prices were stripped. SR1 rows are one-month futures quotes and are not turned into a meeting path.

The yardstick is the US two-year, a proxy. Full-sample daily standard deviation is 5.42 bp. Scaled by the square root of 40 trading days that is 34.3 bp. The declined receive loses if the implied rate rises to 4.53, a 29 bp giveback equal to the two-year's net decline across its last 20 observations. The judgmental band 4.08 to 4.12 is the proxy tail and the proxy day, not a fair value. The declined pay loses if the implied rate falls to 3.94, the overnight fixing, 30 bp below the settle. That level uses up a description of March as sitting above cash. It is not a forecast that the future converges to the fixing. Gap stress on the receive illustration is 4.70. Gap stress on the pay illustration is 3.78.

DV01 for these illustrations is USD 25 per bp per USD 1 million. A study budget of USD 10,000 on the declined receive buys about USD 13.8 million of notional. The same budget on the declined pay buys about USD 13.3 million. At a USD 10 million compare size the receive's adverse loss is USD 7,250 and the pay's is USD 7,500. Those study budgets are not funded. The funded row is flat, draw zero, financing zero. A 70-day charge on a USD 10,000 study draw would have been USD 76.61 and is not taken.

The labor limit is what makes the flat honest. A September score near its anchor, a stale warm inflation score, claims rows without numbers, and no October or November employment print leave a strong US labor story and a weak US labor story both open. In the strong story, 4.24 is too low and the receive is the loser. In the weak story, the pay toward the 3.94 fixing is the loser, and the gap still would not have been carry. Canadian labor components are unavailable, so a strong or weak Canadian story cannot fill the US hole and cannot identify SR3H7. Incomplete evidence narrows the conclusion to flat. It does not authorize a smaller receive or a smaller pay as a compromise.

The mean-reverter would close a March receive because 30 bp over cash is no longer a fade. The gap arithmetic is real, and it is a reason not to add a receive. The trend-follower would add USD 25 million because March has not fully followed the coupon rally. That claim needs an SR3 history this map does not have, and Nasdaq closed at the low of its stored history, so the equity market on the day was not high. The rate-hawk would open USD 10 million short December SOFR. That is the nearest-contract substitution declined above, and the September gap over cash is not a hike count.

## 5. Recommended set, adverse paths

The recommended set is the sized CORRA receive, the EURUSD long at USD 5 million, and nothing else.

| Path | CORRA | EURUSD | Directional sum | Financing, separate |
| --- | ---: | ---: | ---: | ---: |
| Canada reaccelerates, euro unchanged | −100,000 | 0 | −100,000 | about 4,053 |
| Dollar demand and oil, CORRA unchanged | 0 | −41,875 | −41,875 | about 4,053 |
| Both adverse, no correlation assumed | −100,000 | −41,875 | −141,875 | about 4,053 |
| Gap stress, 3.40 and 1.113 | −167,066 | −41,875 | −208,940 | about 4,053 |
| Status quo, USD 100 million plus USD 5 million, both adverse | −208,750 | −41,875 | −250,625 | 8,044.17 |

The financing line on the recommended rows is the scaled CORRA draw plus the EUR draw, 70 days at 3.94 percent ACT/360. The status-quo financing line is the quant file's comparison on a USD 1,000,000 CORRA draw plus the EUR draw. Correlation is a comment. A shared growth scare is not a hedge requirement, and the different notionals are not proof of diversification. The near CORRA target and the near euro target, if both printed, would be about USD +14,970 and USD +58,803. Those are the edges of judgmental ranges, not a base case.

## 6. Decision sheet

The sheet Kevin reviews is the table at the top and the cards in `docs/research/chatgpt/2026-11-06-growth-shock-decision/decision_cards.json`. In short:

- Cut the CORRA 2027 H/M/U/Z receive to USD 47,904,192. Entry is the frozen average 3.05125, now rather than after 3.02 prints. Target 2.98 to 3.02 over 8 to 12 weeks. Yardstick is the Canada two-year proxy. Falsifier is 3.26, or the 30 October oil closes with a warmer underlying inflation impulse, or a real labor reacceleration once labor exists, or Bank of Canada communication on 9 December that validates the higher path. Exit at 3.26. Gap stress 3.40. Budget USD 100,000, which is also the planned-exit loss. Target payoff about USD 14,970 to USD 34,132. Financing about USD 3,670 on a USD 479,042 draw.
- Hold EURUSD at USD 5,000,000. Review a daily close at or below 1.1179. Exit through 1.113 or if WTI returns to 104.12 or Brent to 117.64. Targets 1.1356 and 1.1467. Budget USD 45,000. Adverse loss USD 41,875. Planned-exit loss USD 20,046. Financing USD 383 on a USD 50,000 draw. The yield-gap sensitivity of about USD 14,681 is not a forward.
- No AUDJPY short and no AUDNZD short.
- No SR3 receive and no SR3 pay. The contract that would have been used is March 2027. December is the wrong risk. Wait for a print the packet does not contain, or for March itself at 4.53 or at 3.94.

## 7. Limitations

Derived meeting prices are excluded, so policy inference is coarser than the packet's meeting object, and the 8 bp warning was not turned into a repaired price. There is no CORRA strip history and no SR3 strip history. Yardsticks for those books are the Canada two-year and the US two-year. There are no EURUSD forward points. There are no AU-NZ or NZ-US yield histories. S&P and VIX are 4 November. Broad USD ends 30 October. Canada yields end 4 November. Euro-area yields are labeled 6 November and are not backdated. CORRA contract observation times are null. Oil histories include rolls. Canadian labor components are unavailable. US labor in the scored block is September. Core PCE is a retained July release. The scheduled-output commit named in the job was not in this clone. Prior own research commits are memory and are not ancestors of this branch. The canonical book on HEAD is later than the input commit and was not used. Simulated room actions are not market positioning. No win probabilities and no fair values were estimated.

## 8. What would change the view

A Canadian labor print that is actually in a later packet, and that reaccelerates with the underlying inflation score, would remove the residual CORRA receive. Bank of Canada communication on 9 December that treats the higher 2027 path as the one it is comfortable with would do the same. WTI back at 104.12 or Brent back at 117.64 would remove both the receive and the euro long.

An employment print that is weak enough to take SR3H7 toward the 3.94 fixing would reopen the receive question, still without treating the gap as carry. A print that pushes March to 4.53 would reopen the pay. An AU-NZ yield history with a gap that is not just the kiwi's cheap screen would reopen AUDNZD. A yen bid that actually prints against a further equity drop, with the Japan AI-credit headlines and the oil rebound no longer pointing the other way, would reopen AUDJPY. None of those conditions is in this packet.
