# FX memo, 5 November 2026

Input to the ChatGPT discretionary book. This is not an order and not a portfolio decision. The existing book, in `data/pm/books/latest.json` under `pms.chatgpt` only, is long the CORRA 2027 H/M/U/Z strip (`CORRA_2027H-Z`, asset class rates, notional 250,000,000 USD). It contains no FX position. Figures below are recomputed in `fx_facts.json` unless labeled as a snapshot field or as a judgment. Percent changes are shown to two decimals. The unrounded values are in the JSON.

## Freeze and clocks

The snapshot path is `data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json`.

The SHA256 of the file bytes is `13a1b1ca0fb89f4030f427f4106199ab8087894e478db8e980e1cc1d050f2744`. That digest does not equal the instructed freeze id. The instructed id `0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10` equals the snapshot's own `packet_sha256` and equals the SHA256 of the canonical JSON (`indent=2`, `sort_keys=True`, trailing newline) with the `packet_sha256` field removed. The SHA256 of the canonical full object equals the file-byte digest. Both results are recorded. The difference is not repaired.

Freeze `as_of` is `2026-11-05T04:53:53.458055-05:00`. `families.market_state.as_of` and `market_state.data.generated_at` are both `2026-11-05T10:17:36Z`. FX `source_observation` is `2026-11-04`. Not every field was known at the earlier timestamp. News `as_of` matches the freeze clock. Headlines inside `families.news.items` are narrative. The mark is the stored series.

Each liquid series used here has `n` equal to 252 and `len(history)` equal to 126. The 252 field is not a row count. Snapshot `ret_1d`, `ret_5d`, `ret_1m`, and `ret_3m` on the FX pairs differ from the recomputed one-step, five-observation, 21-observation, and 63-observation simple percents by less than 0.000001 percentage point. Those snapshot returns count stored observations. Calendar anchors are reported separately. No series is forward-filled.

The ChatGPT CADNOK hypothesis (`stated_at` `2026-11-04T22:07:17.587465-05:00`, revision 02) is a prior to challenge. The 4 November closes sit in this packet and precede that timestamp. They are newly admitted context. They are not a score of the forecast.

## What the stored histories show

WTI and Brent, and every G10 USD pair plus the named crosses, last print on `2026-11-04`. The previous stored date is `2026-11-03`. The five-observation window starts on `2026-10-28`. Simple percent is \(100 \times (new/old - 1)\). Log percent is \(100 \times \ln(new/old)\).

| Series | 3 Nov | 4 Nov | Last step simple | Last step log | Five-obs simple | Five-obs log |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| WTI | 96.09 | 88.12 | -8.29 | -8.66 | -14.26 | -15.39 |
| BRENT | 103.60 | 94.62 | -8.67 | -9.07 | -17.95 | -19.78 |
| EURUSD | 1.1179 | 1.1267 | +0.79 | +0.78 | +1.20 | +1.20 |
| GBPUSD | 1.3411 | 1.3500 | +0.66 | +0.66 | +1.60 | +1.59 |
| AUDUSD | 0.6984 | 0.7015 | +0.45 | +0.45 | -0.25 | -0.25 |
| NZDUSD | 0.5624 | 0.5637 | +0.22 | +0.22 | +0.42 | +0.42 |
| USDJPY | 158.29 | 158.25 | -0.02 | -0.02 | +0.18 | +0.18 |
| USDCHF | 0.8199 | 0.8155 | -0.54 | -0.54 | -1.82 | -1.84 |
| USDCAD | 1.3975 | 1.3935 | -0.29 | -0.29 | -0.79 | -0.79 |
| USDNOK | 9.2303 | 9.2278 | -0.03 | -0.03 | -0.72 | -0.72 |
| USDSEK | 9.7965 | 9.7380 | -0.60 | -0.60 | -1.94 | -1.96 |
| CADNOK | 6.6047 | 6.6219 | +0.26 | +0.26 | +0.08 | +0.08 |
| EURNOK | 10.3185 | 10.3970 | +0.76 | +0.76 | +0.48 | +0.48 |
| EURCAD | 1.5623 | 1.5701 | +0.50 | +0.50 | +0.40 | +0.40 |
| AUDCAD | 0.9760 | 0.9776 | +0.16 | +0.16 | -1.04 | -1.05 |
| EURJPY | 176.95 | 178.30 | +0.76 | +0.76 | +1.39 | +1.38 |
| NOKSEK | 1.0613 | 1.0553 | -0.57 | -0.57 | -1.23 | -1.24 |
| AUDNZD | 1.2417 | 1.2445 | +0.23 | +0.23 | -0.67 | -0.67 |

Levels in the table are the stored closes rounded for display. CADNOK's stored closes are 6.6046854 and 6.62187122. The five-observation CADNOK simple change is +0.075209 percent.

Observation horizons, with the actual start date. For WTI and Brent the 21-observation start is `2026-10-06` and the 63-observation start is `2026-08-06`. For the FX rows the 21-observation start is `2026-10-06` and the 63-observation start is `2026-08-07`.

| Series | 21-obs simple | 63-obs simple | 63-obs sign | Calendar ~30d | Calendar ~91d |
| --- | ---: | ---: | --- | --- | --- |
| WTI | -1.48 | +14.01 | positive | -1.46 from 2026-10-05 | +17.15 from 2026-08-05 |
| BRENT | -5.93 | +14.70 | positive | -5.68 from 2026-10-05 | +19.09 from 2026-08-05 |
| EURUSD | -0.02 | -2.32 | negative | +0.56 from 2026-10-05 | -2.48 from 2026-08-05 |
| GBPUSD | +1.68 | +0.37 | positive | +2.08 from 2026-10-05 | +0.16 from 2026-08-05 |
| AUDUSD | +0.47 | -0.36 | negative | +0.79 from 2026-10-05 | -0.52 from 2026-08-05 |
| NZDUSD | +0.35 | -3.99 | negative | +0.81 from 2026-10-05 | -3.99 from 2026-08-05 |
| USDJPY | +0.10 | -0.05 | negative | +0.01 from 2026-10-05 | +0.42 from 2026-08-05 |
| USDCHF | -1.81 | +0.64 | positive | -1.87 from 2026-10-05 | +0.82 from 2026-08-05 |
| USDCAD | -2.21 | -0.53 | negative | -2.23 from 2026-10-05 | -0.80 from 2026-08-05 |
| USDNOK | -3.52 | -3.01 | negative | -3.89 from 2026-10-05 | -2.93 from 2026-08-05 |
| USDSEK | -2.39 | +2.62 | positive | -3.04 from 2026-10-05 | +2.62 from 2026-08-05 |
| CADNOK | -1.34 | -2.50 | negative | -1.70 from 2026-10-05 | -2.15 from 2026-08-05 |
| EURNOK | -3.53 | -5.27 | negative | -3.35 from 2026-10-05 | -5.34 from 2026-08-05 |
| EURCAD | -2.22 | -2.84 | negative | -1.68 from 2026-10-05 | -3.26 from 2026-08-05 |
| AUDCAD | -1.74 | -0.89 | negative | -1.46 from 2026-10-05 | -1.31 from 2026-08-05 |
| EURJPY | +0.08 | -2.38 | negative | +0.58 from 2026-10-05 | -2.08 from 2026-08-05 |
| NOKSEK | +1.17 | +5.81 | positive | +0.89 from 2026-10-05 | +5.72 from 2026-08-05 |
| AUDNZD | +0.13 | +3.79 | positive | -0.03 from 2026-10-05 | +3.61 from 2026-08-05 |

EURUSD's 21-observation change from 6 October is -0.02 percent. The calendar anchor on 5 October is +0.56 percent. The one-month sign depends on the anchor. The quarter is negative on both the 63-observation window and the 91-day calendar anchor.

Both oil series carry the snapshot note that the history is a daily futures close and that contract rolls can distort screens. The path below is the stored futures path.

## Already in the path, and the close this packet adds

The oil decline did not start on 4 November.

| Window | WTI simple | Brent simple |
| --- | ---: | ---: |
| 30 Oct to 2 Nov | -7.36 | -10.94 |
| 2 Nov to 3 Nov | -0.38 | -1.12 |
| 30 Oct to 3 Nov | -7.71 | -11.93 |
| 3 Nov to 4 Nov | -8.29 | -8.67 |
| 30 Oct to 4 Nov | -15.37 | -19.57 |

WTI levels on those dates are 104.12, 96.46, 96.09, and 88.12. Brent levels are 117.64, 104.77, 103.60, and 94.62. The 30 October-to-4 November WTI level change is -16.0. Brent's stored maximum in the 126 closes is 117.64, the 30 October print. WTI's stored maximum is 108.66, so the 30 October WTI close of 104.12 is not the sample high.

Through 3 November, inside the first 125 stored closes, WTI at 96.09 had a weak inclusive rank of 76.0 and a range position of 0.69. Brent at 103.60 had a weak inclusive rank of 71.2. CADNOK at 6.6046854 was the minimum of those 125 closes (`count_below` 0). That low, and the oil drop from 30 October through 3 November, were already in the history before the last print.

The 4 November print is the new close: oil down another 8.29 percent (WTI) and 8.67 percent (Brent), EURUSD up 0.79 percent, CADNOK up 0.26 percent. The prior text already writes those same closes. They remain context. They do not confirm the forecast.

Over the stored sample, from 7 May, WTI is -7.06 percent and Brent is -5.44 percent. Over 63 observations, from 6 August, WTI is +14.01 percent and Brent is +14.70 percent. The calendar 91-day changes, from 5 August, are +17.15 and +19.09 percent. The quarter is still higher. The full stored window is lower. The last few sessions gave back the late-October spike.

## Oil after the drop is near the middle of this sample

Inside the 126 stored closes, weak inclusive rank is \(100 \times\) (count of values at or below the last) / 126.

WTI at 88.12: 56 of 126 closes are at or below it, weak inclusive rank 44.44, midrank 44.05, sample z versus the prior 125 closes -0.06. The stored minimum is 68.55, the median is 89.44, the maximum is 108.66, and the last close sits at range position 0.49. The last daily log return is -2.43 sample standard deviations of the last 20 stored daily log returns.

Brent at 94.62: 62 of 126 closes are at or below it, weak inclusive rank 49.21, midrank 48.81, sample z -0.03. Minimum 71.57, median 94.82, maximum 117.64, range position 0.50. The last daily log return is -2.34 sample standard deviations of its last 20 stored daily log returns.

The snapshot's own series percentile is 56.35 for WTI and 59.13 for Brent. Its series z is +0.44 and +0.45. Neither percentile nor z matches the rank inside the 126 stored rows. The snapshot field uses an `n` of 252 that is not stored here, and the opportunities method says baselines exclude the latest observation. The mismatch is left as a mismatch.

**Judgment.** Both objects put the post-drop level in the middle of their reference sample. A large one-day futures decline left oil near the median of the closes this packet actually stores. The three-month change is positive, so the drop interrupted a rise from early August. It did not finish a three-month decline, and it did not leave a tail-low level inside this window.

## Channels

Non-USD currency versus the dollar on the 3-to-4 November step, measured as the percent change in dollars per unit of that currency:

| Currency | Versus USD, simple percent |
| --- | ---: |
| EUR | +0.79 |
| GBP | +0.66 |
| SEK | +0.60 |
| CHF | +0.55 |
| AUD | +0.45 |
| CAD | +0.29 |
| NZD | +0.22 |
| NOK | +0.03 |
| JPY | +0.02 |

Log identities on that step, residual about zero, so the crosses are the USD legs:

- \(\log\) CADNOK \(= \log\) USDNOK \(-\log\) USDCAD \(= -0.026 - (-0.286) = +0.260\)
- \(\log\) EURNOK \(= \log\) EURUSD \(+\log\) USDNOK \(= 0.784 + (-0.026) = 0.758\)
- \(\log\) EURJPY \(= \log\) EURUSD \(+\log\) USDJPY \(= 0.784 + (-0.024) = 0.760\)
- \(\log\) AUDNZD \(= \log\) AUDUSD \(-\log\) NZDUSD \(= 0.225\)
- \(\log\) NOKSEK \(= \log\) USDSEK \(-\log\) USDNOK \(= -0.573\)

CAD rose versus the dollar (USDCAD -0.29 percent, which is +0.29 percent in dollars per CAD) and rose versus NOK (CADNOK +0.26 percent). NOK versus the dollar was +0.03 percent. The CADNOK rise is the Canadian leg. NOK did not fall against the dollar on the oil-down day. Over the five observations from 28 October, while WTI fell 14.26 percent and Brent fell 17.95 percent, CADNOK rose 0.075 percent. CADNOK's own last day was +0.96 sample standard deviations of its last 20 daily log returns. The oil day was a large move in oil's own recent volatility. The cross day was ordinary.

AUD rose 0.45 percent versus the dollar on the same oil-down day. Its five-observation change is -0.25 percent. SEK rose 0.60 percent versus the dollar and NOKSEK fell 0.57 percent, so the krone weakened against the Swedish krona while oil fell. EURNOK's +0.76 percent is the euro's move plus a flat Norwegian leg.

**Energy, importer against exporter.** The day does not show one oil beta for CAD, NOK, and AUD. CAD and AUD strengthened versus the dollar while oil fell. NOK was unchanged versus the dollar. EUR, an oil importer on the usual map, rose 0.79 percent. JPY, also an importer on that map, rose 0.02 percent. Falling oil can support global demand and hurt producer income at the same time. This packet's cross-section does not separate those two effects into a stable ranking of CAD, NOK, and AUD.

**Judgment.** The same-day Canadian and Norwegian response is evidence about the beta. A cross that did not move with an 8 percent oil decline is a small realized beta for that session. It is not a backlog of unfinished repricing, and the percentile of CADNOK is not a fair-value gap.

**Growth and risk appetite.** The Dow has a 4 November close: 51,786.72 to 53,356.12, level change +1,569.4, simple +3.03 percent. Nasdaq has a 4 November close: 25,372.01 to 25,736.51, level change +364.5, simple +1.44 percent. S&P 500 ends on 3 November (7,541.4 to 7,568.92, +0.36 percent). VIX ends on 3 November (21.15 to 20.83). HY OAS ends on 3 November at 340 bp, snapshot percentile 98.21, stored weak rank 98.41. Copper on 4 November is +0.38 percent. There is no 4 November S&P, VIX, or credit print. A missing print is left missing.

**Geopolitical dollar demand.** No geopolitical quantity is in the market series. Gold rose from 3,940.40 to 4,073.0 on 4 November, simple +3.37 percent, and remains low in its stored window (weak rank 18.25; snapshot percentile 11.51, which also does not match that rank). CHF rose 0.55 percent versus the dollar and JPY rose 0.02 percent. BROAD_USD ends on 30 October at 121.6656. Its last step, 29 to 30 October, is -0.06 percent. Its snapshot percentile is 96.03 and its stored weak rank is 96.83. There is no post-election broad-dollar index in the packet.

**Domestic policy, as far as the curves and yields go.** On 4 November the US 2-year went from 461.0 bp to 458.0 bp (-3.0 bp), the US 10-year from 495.0 to 490.0 (-5.0 bp), the US 30-year from 532.0 to 528.0 (-4.0 bp), and the 10-year breakeven from 230.0 to 226.0 (-4.0 bp). The arithmetic gap between the nominal 10-year change and the breakeven change is -1.0 bp. That is not a real-yield print. US_REAL10 ends on 3 November at 265.0 bp, up 3.0 bp from 2 November. EA 2-year went from 305.0 to 306.0 (+1.0 bp) and EA 10-year from 331.0 to 332.0 (+1.0 bp). The US minus EA 2-year gap is 156.0 bp on 3 November and 152.0 bp on 4 November. That gap is a sovereign yield difference. It is not FX financing. JP 2-year and 10-year step from 2 November to 4 November (+1.1 bp and +3.8 bp) and skip a weekday, so that step is not a one-day election move. CA 2-year ends on 3 November at 326.0 bp, unchanged on its last stored step. AU 2-year and 10-year end on 28 October. No NOK yield series is in the packet.

The news file, used only as narrative, says Democrats flipped the Senate and the House, that oil fell, that the Dow soared about 1,500 points, that the dollar dipped, and that Treasury yields fell. One 4 November headline describes an election stock sell-off. The stored Dow and Nasdaq rose on 4 November. The "below $90" oil headline matches the WTI close at 88.12 and does not match Brent at 94.62. The dollar-dip headline has no BROAD_USD mark after 30 October. The Norges item, with a retrieved summary, says Norway kept the policy rate steady and kept the option of another hike. A 5 November headline says yields continued to fall. The yield mark in the series is the 4 November close.

**Judgment.** The coherent price fact is a modest dollar decline against Europe (EUR, GBP, SEK, CHF), a small Canadian rise, a flat yen, and a flat krone, on a day when US bond yields fell a few basis points, European bond yields rose one basis point, and oil futures fell about 8 percent back to the middle of their stored window. Risk appetite is not a single sign: the equity indices that have a 4 November close rose, and credit has no 4 November close after sitting near the top of its stored spread range on 3 November.

## Curves and financing

ESTR's tradable status is unavailable, with zero contracts. The EA policy path status is partial, the terminal is null, and the three-month contract list is empty. ECB government zeros exist for `aaa` and `all_ratings` as of 3 November, with four nodes each. That is not an ECB futures path. NZ is absent from the official, tradable, and policy curve sets. `NZ_2Y` and `NZ_10Y` are ten-point sovereign series as of 4 November. They are not a futures curve. NOK is absent from all three curve sets, and the rate-series search returns no NOK id. SOFR, CORRA, AONIA, and TONA are present with status ok. Missing ECB and NZ futures curves block a precise euro or New Zealand rate-path comparison with the US and Canadian futures strips. They do not ban a spot idea. The absence of any NOK rate in the curve set blocks a precise NOK-versus-CAD or NOK-versus-EUR policy comparison. Spot can still be described. It cannot be financed from a NOK curve that is not in the packet.

FX pair objects have no forward-points field. Keyword paths under `market_state` that contain "forward" are government-curve forward rates or a macro look-ahead flag. They are not FX points. `opportunities.carry` has six rows (USDCAD, AUDCAD, AUDNZD, NZDCAD, NZDUSD, AUDUSD). Each reason string says the row is a 2-year sovereign yield differential divided by 60-day FX volatility, and that it is not forward carry, funding, roll-down, or expected return. There is no carry row for EURUSD, CADNOK, EURNOK, USDNOK, EURJPY, or USDJPY. The USDCAD row's 135.0 bp differential as of 3 November equals the US minus CA 2-year gap on that date. That reconciliation does not turn the row into a forward.

**Financing of every FX expression reviewed here is UNKNOWN.** A yield gap, including the 152 bp US-EA 2-year gap on 4 November, does not establish a spot direction. A financing benefit, were one present, would not establish a spot direction either.

`opportunities.relationships` is a research prompt. The packet labels `USDCAD~WTI` weak. That label is not used here as a beta or as a vote.

## The expressions

Snapshot `pctile_1y` and `pctile_5y` are copied from `fx.pairs`. They are already on a 0–100 scale. A reading of 0.357143 is the 0.357th percentile. The 126 stored rows cannot recompute a one-year or five-year percentile. A historical rank is a screen. It does not identify fair value.

### Long EURUSD, the leading fresh idea

On 4 November the euro rose 0.79 percent versus the dollar, 2.72 sample standard deviations of its last 20 daily log returns. The five-observation change from 28 October is +1.20 percent, from a stored start of 1.1133. The 63-observation change from 7 August is -2.32 percent. The calendar change from 5 August is -2.48 percent. The 21-observation change from 6 October is -0.02 percent, and the calendar change from 5 October is +0.56 percent.

The snapshot one-year percentile is 8.93 and the one-year z is -1.72. The snapshot five-year percentile is 66.47 and the five-year z is +0.55. Inside the 126 stored closes the weak rank is 18.25. The recent window and the one-year field both look low. The five-year field sits in the upper middle of its scale, with a positive z.

**Continuation versus exhaustion.** The quarter is a lower euro. The last five stored observations are a bounce, and most of that bounce is the last session. Either description fits the path. The five-year rank does not say the bounce is a return to a cheap long-horizon level.

**What appears priced.** The 4 November EURUSD close of 1.1267 already contains the 0.79 percent move. The same day the US-EA 2-year bond gap narrowed from 156 bp to 152 bp. US yields fell a few basis points and EA yields rose one. That is the rate news the spots could have traded. It is not a measured euro futures path, because ESTR is unavailable.

**Reward after financing.** Unknown. There are no EURUSD forward points.

**Horizon and realization.** A long would be realized only by a higher EURUSD spot after this close. Nothing in the packet identifies a residual, net of unknown financing, over the following weeks. The prior CADNOK horizon of two to six weeks is not borrowed for this pair.

**Falsifiers of the long.** EURUSD gives back the 4 November bounce while the US-EA 2-year gap stays near 152 bp. The five-year percentile remains near 66 while the one-year percentile is cited as if it were a five-year extreme. A later packet shows the euro's gain matching a further broad move against the dollar with no euro-specific residual.

**Judgment.** I reject sizing long EURUSD. The one-year rank and the five-year rank are different facts, and the day's move is already in the close.

### Long CADNOK, the challenger

The 3 November close, 6.6046854, was the minimum of the 125 stored closes through that date. The 4 November close, 6.62187122, has four stored closes below it (weak rank 3.97 of 126). The snapshot one-year percentile is 1.785714 and the one-year z is -1.43. The snapshot five-year percentile is 0.357143 and the five-year z is -2.10. The extreme level was already in the path before the last print. The last print lifted the cross off the stored minimum by 0.26 percent.

The 63-observation change from 7 August is -2.50 percent. The calendar change from 5 August is -2.15 percent. NOK strength versus CAD over the quarter was already stored. The five-observation change from 28 October is +0.075 percent.

The log decomposition says the 4 November cross rise equals the Canadian dollar's rise versus the US dollar minus a Norwegian move of about zero. NOK did not weaken against the dollar on the day oil fell 8 percent, nor over the five observations in which oil fell 14 to 18 percent.

The Norges headline says the policy rate was held with the option of another hike. There is no NOK yield, futures curve, or forward point to test that sentence. Financing is unknown.

**Continuation versus exhaustion.** The level still looks like an exhaustion screen on the snapshot five-year scale and inside the stored window. The path over the oil decline did not exhaust it. The cross was flat while oil fell. Continuation of NOK strength versus CAD is what the quarter, and the oil week, already show.

**What appears priced.** The 4 November CADNOK close. The oil move is in the oil series. It is not in a large CADNOK move.

**Reward after financing.** Unknown.

**Horizon and realization.** The prior forecast is conditional and prospective, with no target and no entry, over two to six weeks after further evidence. A long from this packet would be realized by a higher CADNOK spot. The packet does not show a residual that oil has failed to deliver yet. It shows a session, and a five-observation window, in which the cross did not deliver it.

**Falsifiers of the long.** NOK remains bid versus CAD and versus the dollar while oil stays near or below the 4 November closes. That is the evidence already in hand. A later packet that revived the long would need USDNOK higher by a move that is large relative to USDCAD, with oil still at or below 88.12 WTI and 94.62 Brent, and a financing field that is actually a forward.

**Judgment.** I reject sizing long CADNOK. The five-year screen is real as a screen. The oil beta the screen needs did not appear in the data that were supposed to reveal it.

### Other permitted G10 expressions

**Long EURNOK.** Log return +0.758 equals the euro's +0.784 plus USDNOK's -0.026. The day's cross is the euro leg. The snapshot one-year percentile is 2.58 and the five-year percentile is 19.40. The 63-observation change is -5.27 percent. The five-year rank is not the CADNOK tail. I reject it as a second copy of long EURUSD with a flat krone attached.

**Long USDNOK, as Norwegian weakness.** NOK versus the dollar was +0.03 percent on 4 November. USDNOK's 63-observation change is -3.01 percent and its 21-observation change is -3.52 percent, so NOK strength versus the dollar was already the path. Snapshot percentiles are 2.58 (one year) and 8.53 (five years), both low on the 0–100 scale. The oil-down day did not weaken the krone against the dollar. I reject the long.

**Long EURJPY.** Snapshot percentiles are 9.72 (one year) and 81.87 (five years), with z of -1.61 and +1.11. The five-year field is in the upper part of its scale. The last step is the euro plus a yen that was flat versus the dollar (USDJPY -0.02 percent). The 63-observation change is -2.38 percent. I reject the long. The one-year rank and the five-year rank point in different directions, and the yen did not move.

**Short USDJPY.** The yen rose 0.02 percent versus the dollar. The pair's last log return is -0.09 sample standard deviations of its last 20 daily log returns. The snapshot one-year percentile is 52.58. The five-year percentile is 89.01. The US 10-year fell 5 bp and the yen did not rally. I reject the short. A high five-year rank is a screen, and the day's non-response is evidence about the yen's beta to this yield dip.

**Long AUDUSD.** Snapshot percentiles are 49.01 (one year) and 78.69 (five years). The day was +0.45 percent on an oil decline, so the Australian dollar did not trade as oil. The five-observation change is -0.25 percent and the 63-observation change is -0.36 percent. Australian yields end on 28 October. I reject the long.

**Long NZDUSD.** This is the cleanest low rank in the set: snapshot percentiles 8.53 (one year) and 4.17 (five years), stored weak rank 13.49, 63-observation change -3.99 percent from 7 August. The new information is a +0.22 percent day, 0.45 sample standard deviations of the last 20 daily log returns. The low level was already stored. NZ futures are missing. The NZDUSD carry row is a 75 bp 2-year gap as of 4 November, long USD and short NZD, and the row says it is not funding. Financing of the spot is unknown. I reject sizing it. A pre-existing low percentile is not fair value, and a small uptick on a day of broader dollar softness is a muted response.

**AUDNZD.** Snapshot percentiles are 96.23 (one year) and 99.25 (five years). The last step is +0.23 percent. The five-observation change is -0.67 percent. The 63-observation change is +3.79 percent. The near-high is a method example of how a non-response should be read, and it is not an instruction to short AUDNZD. The cross rose on the day. A high percentile is not a short signal. I do not recommend a short.

## Recommendation

**No new FX expression.** Conviction: **low**.

The oil drop is large, two-session, and already partly in the path before 4 November, and the level that remains is near the median of the stored futures history while the three-month change is still positive. The dollar move that did print is a European bid already inside the 4 November EUR, GBP, SEK, and CHF closes. The producer cross the oil move was supposed to reprice, CADNOK, rose 0.075 percent over the five observations that contain the oil drop, because CAD rose against the dollar and NOK did not fall. Financing is unknown for every candidate. I do not size a screen, a one-year rank that disagrees with the five-year rank, or a beta that the oil day itself did not show.

The single strongest reason this could be wrong is that CADNOK's snapshot five-year percentile is still 0.357143, with no NOK rate path in the packet. A slower krone adjustment could still appear in a later packet. That possibility is why the conviction is low. It is not an entry in this one.
