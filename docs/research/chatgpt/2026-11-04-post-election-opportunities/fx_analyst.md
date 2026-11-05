# FX analyst note — 2026-11-04 evidence cycle

Written 2026-11-05 during this execution. Evidence cycle name 2026-11-04. This is a post-cutoff review of a frozen packet plus two authorized post-freeze supplements. It is not a blind forecast as of the morning of 4 November.

Author: Grok 4.7 FX analyst, independent of the rates analyst. Scope is FX. The ChatGPT book's CORRA receive is context. It is not a hedge instruction and it is not a reason to keep or drop an FX idea.

## Evidence boundary

- Packet SHA-256 `d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f`.
- Stated cutoff `2026-11-04T05:35:22.541505-05:00`.
- Market-state `generated_at` `2026-11-04T10:52:31Z`. Both clocks are kept. The later timestamp is when the compact snapshot was generated; it does not move the FX fixing date.
- FX block: `families.market_state.data.fx`, source observation `2026-11-03`, `age_days` 1, `status` ok, 45 pairs. ECB euro reference crosses, one fixing date, deterministic ratios. The source note says these are information and reference rates, not executable prices. Embedded history window starts `2021-10-16`.
- Statistics used: embedded `spot`, `pctile_1y`, `pctile_5y`, `z_1y`, `z_5y`, `ret_1d`, `ret_5d`, `ret_1m`, `ret_3m`, `rv_20d`, `rv_60d` only. No external history, no fair-value model, no event study. Cross-asset series in the snapshot store a level, an observation count, and metadata. They do not store returns, percentiles, or z-scores, so no correlation with oil, copper, equities, gold, or VIX is computed.
- Positioning: CFTC Traders in Financial Futures, futures only, report date `2026-10-27`, `age_days` 8, status ok. Coverage is AUD, CAD, CHF, EUR, GBP, JPY, NZD, plus US Treasury futures. NOK and SEK are absent. CME FX volume and open interest is `unavailable` (HTTP 403 on every mapped G10 product). Positioning status on the snapshot is `partial`. No CFTC FX position is invented for the missing currencies, and the TFF nets are not relabeled as CME open interest.
- NZ cash rates: `unavailable`. The RBNZ B2 workbook returned HTTP 403. Tenors are empty. The snapshot method note says NZ-dependent expressions fail closed. No NZ employment release is invented. AU cash yields are the `2026-10-28` print, `age_days` 7.
- Missing market microstructure, labeled once and applied to every idea: no bid/ask, no forward points, no FX swap carry, no option surface. Spot P&L below is simplified paper accounting on reference rates. Funding that *is* evidenced is separate from FX carry: NY Fed SOFR 3.95 percent, observation date `2026-11-02`, ACT/360, charged on risk capital equal to a 1 percent spot shock (1 percent of USD spot notional), not on exchange margin.

ChatGPT book at the same pin (`data/pm/books/latest.json`, `pms.chatgpt`), evidence cutoff on the book object `2026-11-03T08:22:57.179127-05:00`, decision `2026-11-03T18:36:08.042362-05:00`. One position: long the 2027-03/06/09/12 CORRA strip, entry strip 3.40, mark 3.16, notional $250m, side long, risk capital $2.5m under the 100bp rates shock. Thesis is that the remaining hike premium over CORRA 2.54 percent is rich given Canadian labor and underlying inflation, with Brent described in that decision as around $105. Risk shock also records `spot_fraction` 0.01. Nothing in that position requires an FX overlay.

## Frozen observations

### FX anchors, re-read from the snapshot

All spots are the `2026-11-03` ECB reference. Returns are the stored percent changes. Percentiles are 0–100.

| Pair | Spot | p5 | z5 | r1d | r5d | r1m | r3m |
|---|---:|---:|---:|---:|---:|---:|---:|
| AUDNZD | 1.2417067533 | 98.77 | +2.69 | -0.310 | +0.698 | -0.251 | +3.734 |
| AUDUSD | 0.6983819579 | 76.23 | +0.85 | -0.349 | -0.686 | +0.338 | -0.828 |
| NZDUSD | 0.5624371101 | 3.45 | -1.44 | -0.039 | -1.374 | +0.590 | -4.397 |
| NZDCAD | 0.7860233447 | 1.94 | -1.78 | -0.028 | -1.712 | -1.369 | -4.549 |
| AUDCAD | 0.9760104954 | 88.45 | +1.87 | -0.338 | -1.026 | -1.617 | -0.985 |
| USDCAD | 1.3975310851 | 83.06 | +0.87 | +0.011 | -0.342 | -1.948 | -0.159 |
| USDJPY | 158.2878611683 | 89.25 | +1.08 | +0.246 | +0.296 | +0.037 | +0.289 |
| AUDJPY | 110.5453863935 | 88.21 | +1.63 | -0.103 | -0.392 | +0.375 | -0.541 |
| GBPNZD | 2.3844142134 | 99.88 | +1.82 | -0.025 | +2.023 | +0.812 | +4.162 |
| NZDNOK | 5.1914369088 | 0.04 | -2.66 | -0.278 | -2.293 | -3.299 | -7.411 |
| CADNOK | 6.6046853997 | 0.04 | -2.15 | -0.250 | -0.591 | -1.957 | -2.998 |
| NOKJPY | 17.1488103891 | 98.53 | +2.31 | +0.487 | +1.239 | +4.060 | +3.553 |

`AUDUSD / NZDUSD`, `AUDCAD / NZDCAD`, and `AUDJPY / NZDJPY` each equal `1.2417067533`, the AUDNZD spot. The three crosses are one fixing. CADNOK and NZDNOK `pctile_5y` print `0.0397`, the bottom of this screen. A one-decimal display rounds that to 0.0. Their `pctile_1y` is `0.20`, also the 1-year floor in this screen.

### Cross-asset levels (no embedded returns)

| Mark | As of | Value |
|---|---|---:|
| WTI futures, CL=F | 2026-11-03 | 96.090 |
| Brent futures, BZ=F | 2026-11-03 | 103.600 |
| Gold futures | 2026-11-03 | 3940.40 |
| Copper futures | 2026-11-03 | 6.3785 |
| S&P 500 | 2026-11-02 | 7541.4 |
| Nasdaq Composite | 2026-11-03 | 25372.01 |
| Dow Jones | 2026-11-03 | 51786.72 |
| Russell 2000 | 2026-11-03 | 2812.45 |
| VIX | 2026-11-02 | 21.15 |
| Broad trade-weighted USD | 2026-10-30 | 121.6656 |
| US high-yield OAS | 2026-11-02 | 343 bp |
| US 10Y breakeven | 2026-11-03 | 230 bp |
| US 10Y real yield | 2026-11-02 | 262 bp |

These oil marks are the freeze. They are not the later article's roughly $88 WTI and $94 Brent. Equity marks stop on 2–3 November. There is no post-election equity print in the packet. The broad dollar is five days older than the FX fix and has no percentile here.

Canada Prima-pressure proxy: direction STABLE, strength low, confidence high, front-shock class `parallel_upward_repricing`. Versus the July 2026 MPR conditioning date `2026-07-09`, Brent end-2027 is described as +14.88 dollars per barrel versus a 70 dollar assumption. Largest drivers listed: Brent last-day 2027-12 one-month change +3.6 percent, Brent 2028-12 one-month +2.7 percent, IPPI ex-energy month +0.28 percent. Subcomponents: shock persistence RISING, consumer-price breadth RISING, imported pressure FALLING, production-network pressure STABLE, demand pass-through STABLE. CORRA 2.54 versus a stated neutral midpoint of 2.75, gap about -21 bp. This is a back-curve and inflation-channel proxy. It is not a front-month return for WTI or Brent, and it is not aligned to the FX 3-month window.

### Cash yields and tradable policy paths

| Curve | Obs | 2Y | 10Y | 30Y or long | Notes |
|---|---|---:|---:|---:|---|
| US | 2026-11-03 | 4.61 (p5 79.4, +2 bp 1d, -22 bp 1m) | 4.95 (p5 97.2, +4 bp 1d, -33 bp 1m) | 5.32 (p5 97.7, +4 bp 1d, -31 bp 1m) | 2s10s +34 bp, p1 11.7 |
| CA | 2026-11-02 | 3.26 (p5 56.7, -2 bp 1d, -11 bp 5d) | 3.74 (p5 92.3, -4 bp 1d) | long 4.06 (p5 95.5) | 2s10s +48 bp, p1 1.8 |
| AU | 2026-10-28 | 4.951 (p5 99.0) | 5.208 (p5 97.5) | — | stale for a same-day FX decision |
| EA (Bund) | 2026-11-03 | 3.05 (p5 89.9) | 3.31 (p5 96.4) | 3.68 (p5 95.3) | |
| JP | 2026-11-02 | 1.880 (p5 98.0, z5 +2.48) | 2.817 (p5 95.1, z5 +2.09) | 3.940 (p5 94.5) | front end is the rates extreme |
| NZ | — | empty | empty | — | unavailable |

Cross-country cash spreads on common dates: JP-US 2Y -271 bp (p5 70.7, z5 +0.60) as of 2026-11-02. CA-US 2Y -133 bp (p5 10.1, z5 -1.30). AU-US 2Y +28 bp as of 2026-10-28 (p5 84.9, p1 26.8). AU-NZ 2Y and 10Y unavailable. The US real yield at 262 bp plus the 230 bp breakeven sits next to the 4.95 percent nominal 10Y. The freeze dollar is a high-real-yield dollar. The 1-day US yield change on 3 November was *up* (10Y +4 bp). The 1-month change was a large rally (10Y -33 bp) that predates the election headline.

Tradable futures, implied rate = 100 minus price:

- SOFR 3.95 (2026-11-02). SR3Z6 4.16 (+21 bp), SR3H7 4.365 (+41.5), SR3U7 4.535 (+58.5, local peak), then a slow drift. The strip prices hikes, not cuts. Settlements dated 2026-11-03.
- CORRA 2.54 (2026-11-02). Monthly COAX26 2.515 (-2.5 bp), COAZ26 2.605 (+6.5), COAG27 2.785 (+24.5). Quarterly CRAZ26 2.75 (+21), CRAH27 2.97 (+43), CRAM27 3.115 (+57.5), CRAZ27 3.31 (+77). The book's 2027 H/M/U/Z average was marked at 3.16 in the PM book; this packet's four contracts are 2.97, 3.115, 3.225, 3.31.
- AONIA 4.60 on 03-Nov-2026. November 2026 30-day interbank futures 4.82 (+22 bp), January 2027 4.855. Bank bills 1m/3m/6m 4.72 / 4.89 / 5.24. OIS vintage in the policy block is December 2022 and is unusable. The path prices a further AU hike and then a drift back toward 4.60 by early 2028.
- TONA 1.227 on 2026-10-30. December 2026 3-month futures 1.45 (+22 bp), March 2027 1.6625, June 2027 1.84. Terminal listed at 2031-06 implied 2.655. Hikes are priced. The 30 October CNBC headline says the BoJ held, with underlying inflation described as aligned with 2 percent. Body not retrieved.
- €STR 2.445 on 2026-11-03. Eurex FST3 settlements unavailable. No euro policy path in futures.

Temperature levels use the structural anchor (50 = policy/trend neutral), reference periods mostly through 2026-Q3 or 2026-09, score file refreshed 2026-11-04. They are not a daily nowcast.

- NZ: labor level 36.5, class cool, impulse -2.2, reference 2026-Q2. Activity level 51.9, impulse -16.9, reference 2026-08. Inflation level 64.3, class warm, impulse +4.3, reference 2026-Q2. Consumer impulse -4.7.
- AU: inflation 67.3 warm, labor level 45.7 with impulse -4.4, activity impulse +2.2. AU labor is cooling; AU activity is not printing the NZ-sized negative impulse.
- US: inflation 63.1 warm, activity and labor near 51. CA: labor 40.9, inflation 54.3 static. EA: inflation 64.5 warm, activity impulse -4.3. JP: consumer level 33.7 cool with a positive impulse, inflation 52.5.

The NZ growth impulse is the weak outlier versus Australia. NZ inflation is warm on a stale quarterly reference. That combination can justify a cheap NZD. It is not an employment release, and it is not a policy path.

### News inside the 24-item freeze

Cutoff on the news family matches the packet cutoff. Reuters live check failed with HTTP 401. Many CNBC rows are headline-only. Verification on the rows read is `single_source`.

Energy and Hormuz, which is the oil regime the 3 November FX fix sat in:

- 2026-10-20, "Iran Strikes More Ship Engine Rooms in Ramp-Up of Hormuz Attacks." Snippet: attacks are hitting more ships and doing more damage, with fresh risks to energy flows. No source name and no URL on the frozen row.
- 2026-10-30 03:12 ET, CNBC headline only: "Iran claims four tankers struck mines in Hormuz as strike fears grow after U.S. midterms." The calendar date is before 4 November. The phrase "after U.S. midterms" is left as a frozen-headline inconsistency, not resolved.
- Undated, "Global Oil Supply Buffer Running 'Scarily Thin,' Aramco CEO Says." Snippet: stockpiles are thin unless Hormuz reopens.
- Undated, "LNG Trade Through Hormuz Extends Rebound Despite Shipping Risks." Snippet: LNG shipments rebounded from September.
- 2026-11-01 20:29 ET, Bloomberg: Xi hosted Oman's sultan with Hormuz shipping in focus. Summary: China offered help on safe passage. This is a diplomatic headline sitting next to the attack headlines. The 3 November oil marks were still 96.09 / 103.60.

Election, inside the cutoff, body not retrieved:

- 2026-11-04 04:02 ET, CNBC, headline: "Treasury yields fall as investors crowd into bonds for safety amid election stock sell-off." Transmission tag `usd_rates`, disposition `assess`. The URL path contains `democrats-win-big`. The frozen text that can be used is the headline sentence, not the slug and not a yield level. No equity price accompanies it. The FX fix is still 3 November, so this headline is not in the spots.

Other G10 policy headlines, abbreviated: BoE "ponders a new normal" (2026-11-01) and BoE agents see little energy pass-through into pay (2026-10-29). Japan 2Y auction firm ahead of a BoJ decision where rates were expected to be held (2026-10-28). Fed held (2026-10-28 headlines), chairman described as tough on inflation, 10Y "creeps higher even as Fed keeps rates the same." Bessent played down AI-financing and Fed-path concerns (2026-10-28). A 2026-10-27 piece says bullish Treasury bets face reversal risk from a hawkish Fed. UK dealers see more bill issuance.

RBNZ row, not usable as an NZ shock: 2026-10-27 13:00 ET, Reuters headline "Morning Bid: RBNZ throws markets a curveball." The frozen summary is about CoreWeave and Meta debt, and the URL is a Europe markets view. The curveball is not described. It is not treated as an RBNZ action and not treated as an employment print.

The rest of the window is AI-credit supply (Meta bond sale headline, Alphabet euro bonds, STT GDC loan, a shelved Anthropic-tied data-center sale, BlackRock on the AI debt rush). Relevant to the dollar only as a term-premium and credit-supply backdrop. US 10Y and 30Y are already at the 97th percentile of the 5-year window, with a 2s10s that is flat versus the last year.

### What the 3 November spots already require

The spot complex on the fix requires three things at once.

1. NZD stays the funding-side or growth-discount currency. NZDUSD at the 3.5 percentile, NZDCAD at the 1.9 percentile, NZDNOK and the GBPNZD 99.9 percentile are the same fact in different numeraires.
2. NOK keeps a terms-of-trade premium. USDNOK at the 8.7 percentile, CADNOK and NZDNOK at the sample floor, NOKJPY at the 98.5 percentile. The oil *level* next to that premium is WTI 96.09 and Brent 103.60, with attack headlines still in the packet and Prima shock-persistence marked RISING. The spot requires the premium to be about oil and Hormuz, but the snapshot does not contain the oil return that would measure it.
3. The dollar's rate support stays large. JP-US 2Y at -271 bp, CA-US 2Y at -133 bp, SOFR futures pricing a hike cycle toward the mid-4s, US 10Y real yield 262 bp. USDJPY at 158.29 with a 3-month return of +0.29 percent is a carry stalemate, not a fresh break.

AUD is not in that list. AUDUSD at the 76th percentile of five years and the 39th of one year, with a negative 3-month return, is a mid-pack commodity currency.

## Later CNBC

Authorized supplement only. Not retrieved in this execution. Source updated `2026-11-04T17:11:00Z`, cache `18:01Z`. The receipt minute was not captured. CNBC reporting, not independently verified. None of these quotes is an executable FX price, and none shares a timestamp with the 3 November ECB fix.

Reported political result: Democrats won House and Senate majorities. Senate flips listed: IA, KS, NC, OH, SC, ME, TX. Ohio and Texas governorships also listed.

Narrative yields, kept separate from the quote table: 10Y 4.898, down more than 5 bp; 30Y 5.293, down more than 3 bp; 2Y 4.573, down more than 4 bp. Quote table: 2Y 4.577 and 30Y 5.29. Those two sets are not fused with each other and not subtracted from the freeze (US 2Y 4.61, 10Y 4.95, 30Y 5.32 on 3 November) to manufacture a same-day FX impulse.

Oil: WTI about -8 percent toward $88, Brent about -8 percent toward $94. That is a different oil state from the frozen 96.09 / 103.60.

Attribution in the article, as received: JPM on deficit constraints and a possible shutdown; BondBloxx that divided government may limit deficit growth and that there is no immediate Iran escalation; Vance blamed the Iran war for GOP losses. The oil-to-election link is a hypothesis.

This article is a third clock. It is not the 04:02 ET headline, and it is not Kevin's note.

## Kevin

Post-freeze, not verified, and not an instruction to short AUDNZD.

His observation: AUDNZD is near five-year highs and failed to rally on a dismal NZ jobs print. No date, no magnitude, no intraday path. Preserved as his observation. The 24-item freeze does not contain an NZ employment release. The 3 November fixing cannot confirm or refute a print that was not supplied.

His scenario: de-escalation is the main plausible source of current risk-on, and it could lift AUDNZD while Canadian rates fall. Escalation could raise Canadian rates and hit risk assets and AUD.

That scenario is a different regime from the freeze headline and from the article.

- Freeze headline at 04:02 ET: election stock sell-off and a safety bid into bonds. Risk-off language. No equity mark.
- Kevin: risk-on de-escalation, AUDNZD up, Canadian front end softer.
- Article: lower oil, lower Treasury yields, divided-government deficit constraint, no immediate Iran escalation. Oil down is a terms-of-trade hit for oil currencies, which is not the same statement as "AUDNZD rallies."

Canadian rates falling is already the content of the CORRA receive. It does not tell me the sign of AUDNZD. The relative test below is the check on whether AUDNZD has been behaving like that risk leg.

### The nonresponse, as a conditional exhaustion signal only

A usable exhaustion signal would be: a dated NZ-negative labor print, and AUDNZD failing to extend higher on that print, meaning the short-NZD impulse did not respond to fresh bad news. Kevin's sentence has the shape of that signal and none of the measurements. It is not used as evidence.

What the freeze itself shows on the latest day is a different nonresponse. On 3 November, NZDUSD was -0.04 percent and AUDUSD was -0.35 percent, so AUDNZD fell 0.31 percent because AUD lagged. NZD did not sell off that day. The 5-day and 3-month windows still show NZD lagging and the cross higher. A one-day dip caused by the AUD leg is not exhaustion of the NZD leg. The 1-month window is a stall (AUDNZD -0.25 percent) while both dollar crosses were up, which says the cross stopped trending for a month and does not say why.

I do not promote that one-day AUD lag, or Kevin's undated jobs sentence, into a short AUDNZD.

## Pair screen

Returns in percent. `p5` and `z5` are the embedded 5-year percentile and z-score. Spots are 2026-11-03 ECB references. `p5` is shown to one decimal; CADNOK and NZDNOK are 0.04 unrounded, which displays as 0.0.

| Pair | Spot | p5 | z5 | r1d | r5d | r1m | r3m |
|---|---:|---:|---:|---:|---:|---:|---:|
| AUDCAD | 0.97601 | 88.5 | +1.87 | -0.34 | -1.03 | -1.62 | -0.99 |
| AUDCHF | 0.57262 | 40.8 | -0.36 | -0.31 | -1.73 | -1.00 | +0.42 |
| AUDJPY | 110.545 | 88.2 | +1.63 | -0.10 | -0.39 | +0.38 | -0.54 |
| AUDNOK | 6.44624 | 4.8 | -1.60 | -0.59 | -1.61 | -3.54 | -3.95 |
| AUDNZD | 1.24171 | 98.8 | +2.69 | -0.31 | +0.70 | -0.25 | +3.73 |
| AUDSEK | 6.84169 | 39.7 | +0.12 | +0.02 | -2.09 | -2.13 | +2.65 |
| AUDUSD | 0.69838 | 76.2 | +0.85 | -0.35 | -0.69 | +0.34 | -0.83 |
| CADCHF | 0.58670 | 25.8 | -1.02 | +0.03 | -0.71 | +0.62 | +1.42 |
| CADJPY | 113.262 | 82.5 | +0.99 | +0.24 | +0.64 | +2.02 | +0.45 |
| CADNOK | 6.60469 | 0.0 | -2.15 | -0.25 | -0.59 | -1.96 | -3.00 |
| CADSEK | 7.00986 | 28.0 | -0.91 | +0.36 | -1.07 | -0.52 | +3.67 |
| CHFJPY | 193.050 | 83.7 | +1.16 | +0.21 | +1.36 | +1.39 | -0.96 |
| CHFNOK | 11.257 | 26.2 | -0.41 | -0.28 | +0.12 | -2.56 | -4.36 |
| CHFSEK | 11.948 | 70.4 | +0.58 | +0.33 | -0.37 | -1.14 | +2.22 |
| EURAUD | 1.60070 | 27.4 | -0.40 | +0.02 | +0.95 | -0.56 | -2.34 |
| EURCAD | 1.56230 | 68.4 | +0.75 | -0.32 | -0.08 | -2.17 | -3.30 |
| EURCHF | 0.91660 | 4.4 | -1.26 | -0.29 | -0.79 | -1.56 | -1.93 |
| EURGBP | 0.83358 | 7.2 | -1.56 | -0.27 | -0.36 | -1.61 | -2.74 |
| EURJPY | 176.950 | 80.0 | +1.03 | -0.08 | +0.56 | -0.19 | -2.87 |
| EURNOK | 10.319 | 16.7 | -1.28 | -0.57 | -0.67 | -4.08 | -6.20 |
| EURNZD | 1.98760 | 86.0 | +1.33 | -0.29 | +1.66 | -0.81 | +1.31 |
| EURSEK | 10.951 | 35.1 | -0.37 | +0.04 | -1.16 | -2.67 | +0.25 |
| EURUSD | 1.11790 | 63.6 | +0.37 | -0.33 | +0.26 | -0.22 | -3.15 |
| GBPAUD | 1.92027 | 56.3 | +0.13 | +0.29 | +1.32 | +1.07 | +0.41 |
| GBPCAD | 1.87421 | 92.2 | +1.25 | -0.05 | +0.28 | -0.57 | -0.58 |
| GBPCHF | 1.09959 | 30.9 | -0.45 | -0.03 | -0.43 | +0.05 | +0.84 |
| GBPJPY | 212.277 | 90.4 | +1.35 | +0.18 | +0.92 | +1.44 | -0.13 |
| GBPNOK | 12.379 | 25.0 | -0.83 | -0.30 | -0.32 | -2.51 | -3.56 |
| GBPNZD | 2.38441 | 99.9 | +1.82 | -0.03 | +2.02 | +0.81 | +4.16 |
| GBPSEK | 13.138 | 64.6 | +0.37 | +0.30 | -0.80 | -1.08 | +3.07 |
| GBPUSD | 1.34108 | 79.7 | +0.99 | -0.06 | +0.62 | +1.41 | -0.42 |
| NOKJPY | 17.149 | 98.5 | +2.31 | +0.49 | +1.24 | +4.06 | +3.55 |
| NOKSEK | 1.06135 | 93.1 | +1.52 | +0.61 | -0.48 | +1.47 | +6.88 |
| NZDCAD | 0.78602 | 1.9 | -1.78 | -0.03 | -1.71 | -1.37 | -4.55 |
| NZDCHF | 0.46116 | 8.5 | -1.31 | -0.00 | -2.41 | -0.75 | -3.19 |
| NZDJPY | 89.027 | 61.9 | +0.28 | +0.21 | -1.08 | +0.63 | -4.12 |
| NZDNOK | 5.19144 | 0.0 | -2.66 | -0.28 | -2.29 | -3.30 | -7.41 |
| NZDSEK | 5.50991 | 14.9 | -1.43 | +0.33 | -2.77 | -1.88 | -1.04 |
| NZDUSD | 0.56244 | 3.5 | -1.44 | -0.04 | -1.37 | +0.59 | -4.40 |
| SEKJPY | 16.158 | 82.6 | +1.19 | -0.12 | +1.73 | +2.56 | -3.11 |
| USDCAD | 1.39753 | 83.1 | +0.87 | +0.01 | -0.34 | -1.95 | -0.16 |
| USDCHF | 0.81993 | 26.4 | -0.94 | +0.04 | -1.05 | -1.34 | +1.26 |
| USDJPY | 158.288 | 89.2 | +1.08 | +0.25 | +0.30 | +0.04 | +0.29 |
| USDNOK | 9.23025 | 8.7 | -1.44 | -0.24 | -0.93 | -3.87 | -3.15 |
| USDSEK | 9.79649 | 37.4 | -0.51 | +0.37 | -1.41 | -2.46 | +3.51 |

Screen reading, before any trade is kept. The large absolute 5-year z-scores cluster in two places: NOK strength (NZDNOK -2.66, CADNOK -2.15, NOKJPY +2.31, AUDNOK -1.60, USDNOK -1.44, NOKSEK +1.52) and NZD weakness (NZDNOK, NZDCAD -1.78, NZDUSD -1.44, GBPNZD +1.82, NZDSEK -1.43). AUDNZD at z5 +2.69 is the overlap of a very weak NZD and an ordinary AUD, and it is the largest positive z5 in the book. AUDCAD's z5 of +1.87 sits with a 1-year percentile of 42 and negative returns at every horizon in the table, so that 5-year z is a leftover level, not a live impulse. EURGBP is a true two-window extreme (p5 7.2, p1 0.2, z1 -2.91) but the legs point at EUR weakness as much as GBP strength, and there is no sterling cash curve in the packet. USDJPY's p5 of 89 with z5 +1.08 and a flat 1-month and 3-month return is a high level that has stopped moving. Extremes are entry context. The two clusters are the only places a driver is even plausible: an NZD-specific discount, and a NOK premium sitting next to Hormuz headlines and a still-high oil level.

Realized-vol context for the tails: NZDUSD rv20 7.75, AUDNZD rv20 7.97, CADNOK rv20 4.10, EURUSD rv20 4.54, USDJPY rv20 4.15 versus rv60 7.55. CADNOK's low short-horizon vol means the NOK premium has been a grind. NZD's vol means a 1 percent spot shock is an ordinary few days, not a thesis-sized move.

## Relative AUD vs NZD tests

Daily co-movement cannot be estimated. The snapshot does not contain aligned return series for the crosses or for oil. The test uses the four embedded horizons, the cross-identity, and the oil proxies that actually have returns (USDNOK, CADNOK, AUDNOK, NZDNOK, NOKJPY). WTI, Brent, copper, gold, equities, and VIX contribute levels only.

### The cross is the leg gap

Difference of USD-leg returns minus the AUDNZD return. A residual near zero means the cross added no information beyond AUD versus NZD.

| Horizon | AUDUSD | NZDUSD | AUD minus NZD | AUDNZD | Residual (pp) |
|---|---:|---:|---:|---:|---:|
| 1d | -0.349 | -0.039 | -0.310 | -0.310 | -0.00 |
| 5d | -0.686 | -1.374 | +0.689 | +0.698 | +0.01 |
| 1m | +0.338 | +0.590 | -0.252 | -0.251 | +0.00 |
| 3m | -0.828 | -4.397 | +3.570 | +3.734 | +0.16 |

Same exercise in CAD and JPY. Residuals on the 3-month horizon are +0.17 pp (AUDCAD minus NZDCAD versus AUDNZD) and +0.15 pp (AUDJPY minus NZDJPY). The residual is similar across numeraires and grows with the horizon, which is what compounding of large simple returns does. It is not a CAD-specific or JPY-specific story hiding inside the cross.

Economic content of the 3-month row: NZDUSD fell 4.40 percent, AUDUSD fell 0.83 percent. AUD was a drag on AUDNZD over that window. The entire rise in the cross is NZD underperformance. Over one month both dollar crosses rose and NZD rose more, so the cross eased. Over five days both fell and NZD fell about twice as much. Over one day AUD fell and NZD was flat, so the cross fell. AUD has not been the leader in any of the four windows.

### Versus USDCAD

| Horizon | AUDNZD | USDCAD | Same sign |
|---|---:|---:|---|
| 1d | -0.31 | +0.01 | no |
| 5d | +0.70 | -0.34 | no |
| 1m | -0.25 | -1.95 | yes, and the CAD move is about eight times the cross |
| 3m | +3.73 | -0.16 | no |

Three of the four horizons disagree in sign. The agreeing month is a large CAD rally (USDCAD -1.95 percent) beside a quarter-point dip in AUDNZD. AUDNZD has not been a USDCAD clone on these windows. It is a poor stand-in for a Canada-rates or Canada-oil view.

### Versus the oil proxies that have returns

NOK crosses are the oil-linked FX that the snapshot can measure. Front-month WTI and Brent cannot be correlated with AUDNZD from this file.

| Horizon | AUDNOK | NZDNOK | Extra NZD lag vs NOK (pp) | AUDNZD |
|---|---:|---:|---:|---:|
| 1d | -0.59 | -0.28 | -0.31 (AUD lagged) | -0.31 |
| 5d | -1.61 | -2.29 | +0.68 | +0.70 |
| 1m | -3.54 | -3.30 | -0.24 | -0.25 |
| 3m | -3.95 | -7.41 | +3.46 | +3.73 |

Over three months and over five days, NZD lost extra ground to NOK beyond what AUD lost. Over one month the two antipodeans fell by similar amounts versus NOK, and the cross did nothing. Over one day AUD was the laggard versus NOK. NOKJPY was positive at every horizon (3-month +3.55 percent, p5 98.5). USDNOK was negative at every horizon (3-month -3.15 percent). The NOK bid is broad. The AUDNZD bid is not that NOK bid. Where AUDNZD rose, NZD was weakening versus NOK by more than AUD was.

CADNOK's 3-month return is -3.00 percent, so CAD also lost to NOK, by less than AUD and by much less than NZD. Ranking versus NOK over three months, strongest to weakest: CAD, then AUD, then NZD. That ranking is the opposite of a story in which AUDNZD rallies because AUD is the high-beta risk or oil leg.

Copper at 6.3785, gold at 3940, and the equity indexes are levels without returns. They are not used as co-movement evidence. Prima's +3.6 percent and +2.7 percent are one-month changes on deferred Brent contracts, a different object from front-month WTI and from the FX 3-month window.

### What the test allows me to say

AUDNZD on this fix is a short-NZD residual. It does not co-move with USDCAD. It does not behave like the NOK oil complex. It does not show AUD leadership. A de-escalation or risk-on view that "lifts AUD" is an AUDUSD statement, and AUDUSD is not the extreme. A view that the NZD discount is too large is an NZDUSD (or NZDCAD, or NZDNOK) statement. Putting both inside AUDNZD sells a currency that is not rich on its own dollar cross and buys a currency whose discount may be the point.

Kevin's long AUDNZD therefore does not survive as the expression of his own scenario. Over the one month in which both AUD and NZD rose against the dollar, NZD rose more and the cross fell. The windows in which the cross rose are the windows in which NZD was being sold off harder, including against NOK. That is NZD-specific weakness, which his de-escalation story does not explain and which an escalation story would have to explain as NZD beta exceeding AUD beta. The legs do not show that pattern in the oil proxies: NZD underperformed NOK while AUD also underperformed NOK, and CAD held up better than either.

## Judgment

No FX expression is READY on the 3 November spots. The packet already contains a 4 November 04:02 ET risk-off headline with no accompanying FX or equity mark, the oil complex in the freeze is still the Hormuz-stress complex, NZ rates fail closed, and the two supplements describe regimes that contradict each other and the headline. A trade that needs a post-election FX mark or a post-election oil mark is conditional and names the mark. Sizes below are research sketches. They are not orders. They are not additive. If more than one condition cleared, I would still run only the highest-ranked cleared idea at the sketched unit, because a dollar safety bid hurts NZDUSD and EURUSD together, and because CADNOK's oil condition is a different bet.

Funding on every sketch: risk capital = 1 percent of USD-equivalent spot notional. Daily charge = that risk capital times 0.0395 / 360. On a $300,000 risk unit that is about $33 per day. A four-week accrual is a few hundred dollars. It does not change the sign of a 1 percent spot move. It also does not stand in for the missing FX forward points. Swap carry is unknown and is not credited.

CFTC color used below is the 27 October TFF report, eight days before the fix. Asset-manager AUD net -125,237 contracts, -38.5 percent of open interest, 1-year percentile 2.9, z1 -1.72, weekly net change +3,502. Leveraged-fund AUD net +48,414, 1-year percentile 39, 3-year percentile 80. NZD asset-manager net -46,841, -36.3 percent of open interest, 1-year percentile 68 (a large short that is ordinary for NZD). NZD leveraged-fund net -22,554, 3-year percentile 18, weekly -3,274. The crowded real-money short is AUD, not NZD. That fact argues against selling AUD inside a "fade AUDNZD" package. It is not, by itself, a long AUDUSD: the spot is not cheap, and the freeze headline is a risk-off tape the spot has not yet marked.

### 1. Long NZDUSD — CONDITIONAL

Discrepancy. NZD is the cheap leg against USD (p5 3.5, z5 -1.44, 3-month -4.40 percent), against CAD (p5 1.9, 3-month -4.55 percent), against NOK (sample floor, 3-month -7.41 percent), and against GBP (GBPNZD p5 99.9). AUDNZD's 98.8 percentile is this fact. The 1-month NZDUSD return is +0.59 percent, so the 3-month hole has stopped deepening on that horizon, and the 5-day return of -1.37 percent says the bounce has not held.

Priced expectations. The spot already requires a persistent NZD discount. It does not require AUD strength. What it requires in policy space is unknown, because the NZ curve is empty. AU policy, the nearest comparable, prices a hike: AONIA 4.60, November futures 4.82. US policy prices a larger hike cycle from SOFR 3.95. If NZ were pricing an easing cycle, a 3.5 percentile currency could be the mirror of that gap, the way USDJPY at the 89th percentile mirrors a -271 bp front-end gap that is not itself extreme (JP-US 2Y p5 71). That comparison cannot be run.

Causal driver. The driver that *is* in the file is idiosyncratic NZD weakness, lined up with a cool NZ labor temperature (36.5, reference 2026-Q2) and a large negative activity impulse (-16.9, reference 2026-08), beside warm NZ inflation (64.3). The activity gap versus Australia (AU activity impulse +2.2) matches the sign of AUDNZD over three months. Positioning does not explain it: the NZD leveraged-fund short is only moderately low versus three years, and the asset-manager short is a mid-range percentile.

Forecast, conditional, no probability. If the missing NZ curve shows that policy is not priced on an easing path wide enough to account for a bottom-of-range currency, the 3-month underperformance versus USD, CAD, and NOK is too large for the temperature gap alone, and NZDUSD can retrace part of that 4.4 percent over four to eight weeks. If the curve shows a wide easing gap, the currency is tracking policy and the idea is dropped. Judgment only: this is the right instrument for the relative-value result, and the temperature evidence makes it a weak fade until the curve is seen. I am not assigning a probability.

Entry. Not the 3 November spot. The expression is NZ-dependent and fails closed under the packet rule while `NZ_rates` are unavailable. Mark request, all three, after the freeze: (i) RBNZ B2 2Y, 5Y, and 10Y, the source the packet failed to fetch; (ii) a post-2026-11-03 NZDUSD reference from the same ECB family; (iii) one post-election equity or VIX mark against the frozen anchors (VIX 21.15 on 2026-11-02, S&P 500 7541.4 on 2026-11-02, Nasdaq 25372.01 on 2026-11-03). The condition fails if the NZ 2Y is missing, if the new NZ front end is an easing path while AONIA futures price hikes, or if the equity/VIX mark confirms the 04:02 ET stock-selloff headline. No NZ jobs print is assumed. Kevin's print, if it is later documented with a date and a magnitude, is an input to the exhaustion question and is not this entry.

Catalyst path. The catalyst is the curve print plus a regime mark, not a hoped-for payroll. A confirmed safety bid delays the long. A confirmed de-escalation with equities stable and the NZ curve not priced for cuts would open it. Those are two different supplements; both have to be measured, not blended.

Falsifiers. Another 5-day leg of about -1.4 percent or worse after entry. An NZ 2Y that makes the currency look like fair value against the rate gap. A fresh activity or labor impulse as negative as the current -16.9 activity impulse. Oil and AUD paths are not falsifiers, because the relative test says this is not the AUD or the oil trade.

Realization. From the conditional entry, take half off on a +2 percent spot move (about half of the 3-month drawdown, two of these risk units) and review the rest at four to eight weeks. If the 5-day return is again about -1.4 percent, the bounce-stall pattern is intact and the position goes.

Sizing. USD notional $30m. USD per 1 percent spot move: $300,000. Risk capital $300,000, funded at SOFR 3.95 ACT/360, about $33 a day. rv20 is 7.75, so one risk unit is inside a normal week. Chosen below the other sketches because the macro temperature agrees with a discount and the curve is missing.

Adverse path. A repeat of the 3-month NZDUSD decline is about -4.4 percent, roughly -$1.3m on this notional, before the missing spread and before any NZD funding cost. A risk-off print that confirms the election stock-selloff headline is the path that gets there. Liquidity is the ECB reference plus an unknown bid/ask; NZD spreads are not in the file and can eat a small signal. Convexity is spot-linear. There is no option hedge in the snapshot.

Exposures. Growth: long a cool-labor, negative-impulse economy; this is the main fundamental risk. Inflation: NZ inflation temperature is warm, which could support the currency if the bank responds, and the response is exactly what the missing curve would show. Policy: unpriced; fail closed. Fiscal and term premium: no NZ fiscal mark; US term premium is the dollar leg (10Y p5 97, real yield 262 bp). Energy and terms of trade: secondary. NZD already lagged NOK, so this long is not a bet that oil falls or rises. Currency-specific: the entire case. Liquidity and positioning: TFF NZD short is not extreme; CME OI unavailable; reference rate rather than a dealable quote. Carry and funding: FX points unknown; SOFR charge on risk capital is negligible next to spot. Horizon: four to eight weeks. Path: the 1-month bounce has already started and the 5-day has already given it back, so the entry is not a breakout and not a falling knife until the next fix is seen.

### 2. Long CADNOK — CONDITIONAL

Discrepancy. CADNOK at 6.6047 is on the 5-year sample floor (p5 0.04, z5 -2.15) and the 1-year floor (p1 0.20, z1 -1.52). Returns are negative at every embedded horizon: 1-day -0.25, 5-day -0.59, 1-month -1.96, 3-month -3.00. rv20 is 4.10, so this has been a persistent grind, not a one-day spike. NOK is strong against USD, JPY, AUD, EUR, and SEK as well. The CAD leg is the less extreme oil currency: USDCAD p5 is 83, and CAD's 1-month gain versus USD was 1.95 percent.

Priced expectations. The spot requires NOK to keep a large premium over CAD. Given the frozen oil level and the Hormuz attack headlines, that premium is what a stressed oil tape looks like in these crosses. Prima calls the oil-curve shock persistent and the net proxy only STABLE / low, which says the back of the Brent curve has been repriced up and is not currently accelerating into a new inflation vote. The spot does not require a further CADNOK decline to be "fair." It does require a reason to fade a trend that the freeze's own headlines still support. That reason is not in the 3 November marks.

Causal driver. Terms of trade, NOK versus CAD, with Hormuz as the narrative and no measured front-month oil return. Canada is an oil producer too, so this is a relative-beta trade. If oil falls and CAD falls one for one with NOK, CADNOK does not pay. The secondary CAD fact is positioning: leveraged funds' CAD net was -96,747 contracts, -26.8 percent of open interest, 3-year percentile 10.6, z3 -1.20, as of 27 October. A crowded CAD short can lift CADNOK even without oil moving. Part of that squeeze may already be in the 1-month USDCAD rally. NOK has no TFF row, so the NOK leg is unpositioned in this packet.

Forecast, conditional, no probability. If front-month oil is actually marked down on the order of the article's roughly 8 percent decline, toward about $88 WTI and $94 Brent, the NOK premium over CAD is the FX tail most directly tied to the oil stress that would be easing. CADNOK can then retrace on the order of 1.5 percent, about half the 3-month move, over two to six weeks. If oil is still near 96 / 104, the freeze regime is intact and the fade is wrong. The article's oil-to-election link stays a hypothesis. I am not treating a Democratic Congress as an oil model.

Entry. Not the 3 November CADNOK. Mark request, same timestamp, after the freeze: CADNOK from the ECB reference family, WTI, and Brent. The condition is a front-month oil decline of about the article's magnitude from the frozen 96.09 / 103.60, with CADNOK still near or below 6.6047. If oil has not moved, or if CADNOK has already mean-reverted by more than about 1.5 percent before the oil mark, there is no entry. Later article prices are not this mark.

Catalyst path. Confirmed oil de-escalation, which the BondBloxx line in the article ("no immediate Iran escalation") only talks about. The 1 November Xi/Oman safe-passage headline was already in the freeze and did not come with a lower oil mark. A headline without a new oil print does not open the trade.

Falsifiers. WTI and Brent back near the frozen 96 / 104, or a fresh Hormuz disruption headline of the 20 October or 30 October type alongside a lower CADNOK. Canadian rates re-pricing the 2027 CORRA strip back toward the mid-3s in a way that signals a domestic CAD shock rather than an oil move. That rates path is the book's business; it is named here only as a CAD-leg falsifier, not as a hedge ratio. A further CADNOK decline of about 1 percent after a confirmed oil markdown would say NOK's premium was not the oil level.

Realization. From the conditional entry, take the position off on a +1.5 percent CADNOK move, or if oil reverses to the frozen level, whichever comes first. Horizon two to six weeks. Do not hold it as a structural NOK short once the oil mark has round-tripped.

Sizing. USD-equivalent $40m on each leg. USD per 1 percent CADNOK move: $400,000. Risk capital $400,000, about $44 a day at SOFR 3.95 ACT/360. The low rv20 is why this unit is slightly larger than the NZD unit: the residual is a grind, and a 1 percent move is a larger share of recent realized vol.

Adverse path. Another 3 percent grind, the size of the last three months, is about -$1.2m on this notional, with no TFF cover on NOK and an unknown CADNOK spread. The ugly fundamental path is escalation that keeps Brent at or above the frozen 103.60 while CAD is the leg that sells off. Spot-linear. No surface.

Exposures. Growth: Canada labor temperature 40.9 is cool, which is the book's CORRA argument and a mild negative for the CAD leg; it is not why this cross is at the floor. Inflation: Prima consumer breadth RISING, shock persistence RISING, net vote STABLE. An oil markdown that does not stick in Canadian inflation is the overlap with the receive, and it is coincidental, not a hedge. Policy: BoC path prices hikes (CRAH27 2.97 from CORRA 2.54); NOK policy is not in the packet. Fiscal and term premium: not this cross. Energy and terms of trade: the whole trade. Currency-specific: NOK's premium is broad, so the CAD choice is "monitored oil currency with a known curve," not "pure non-oil." SEK would be the cleaner non-oil leg and is rejected below for lack of a curve and a positioning row, and because NOKSEK's 5-day return has already turned. Liquidity and positioning: CAD TFF short is real and stale by eight days; NOK positioning unknown; CME unavailable. Carry and funding: points unknown; NOK's interest rate versus CAD is unknown, so a long CADNOK might be paying carry that this accounting ignores. Horizon: two to six weeks, tied to the oil mark. Path: still making lows into the fix (5-day -0.59 percent). Fading it before the oil mark is fighting the tape the freeze actually contains.

### 3. Long EURUSD — CONDITIONAL

Discrepancy. EURUSD 1.1179 is a 1-year extreme (p1 2.2, z1 -2.24, 3-month -3.15 percent) and not a 5-year extreme (p5 63.6, z5 +0.37). The 5-day return is +0.26 percent and the 1-day is -0.33 percent. Leveraged-fund EUR net -71,574, -8.2 percent of open interest, 1-year and 3-year percentiles both at the floor (0.96 and 0.32), z3 -2.22. Asset-manager net is still long (+173,249) but that long is at the 1-year floor of their own history (p1 0.96, weekly -17,172). Specs are extremely short. Real money has cut.

Priced expectations. The spot requires the last year's EUR drawdown to be the local regime. It does not require EUR to be cheap against the five-year range. The 5-year percentile says a bounce toward the middle of the longer range is a 1-year trade, not a value trade. €STR is 2.445 and the futures strip is missing, so the euro policy path is a cash yield (Bund 2Y 3.05, 10Y 3.31, both high in the 5-year window) without a tradable meeting path. EA inflation temperature is 64.5 warm. Activity impulse is -4.3.

Causal driver. Positioning plus a 1-year price extreme, against a dollar that is supported by real yields at 262 bp and a SOFR strip that prices hikes. The 04:02 ET headline, if the stock sell-off is real, is a reason the dollar extreme can extend. That is why this is not ready on the 3 November fix: the packet already tells me a safety bid may be underway, and the spot has not been re-marked.

Forecast, conditional, no probability. If the post-election equity and VIX marks do not confirm the safety bid, and EURUSD is still at or below 1.1179, the crowded leveraged-fund short is the discrepancy worth owning for two to six weeks, aiming at about half of the 3-month decline. If the safety bid is confirmed, the 1-year extreme can get more extreme and the short is doing the fundamental work. Judgment only, and it ranks behind NZDUSD because the relative test isolated NZD, whereas this is a generic dollar-tactical with a 5-year percentile that is not cheap.

Entry. Not 1.1179 as a fill. Mark request: a post-election-session EURUSD ECB reference, plus either VIX or one of the frozen equity indexes. Condition: EURUSD at or below 1.1179, and the safety bid not confirmed (VIX not materially above 21.15 and equities not materially below the frozen S&P 7541.4 / Nasdaq 25372). "Materially" is deliberately not a fitted threshold; a print that a reader would call a sell-off versus those anchors fails the condition. I will not invent the cutoff in index points.

Catalyst path. Failure of the 04:02 ET safety bid to show up in equities or VIX, with specs still short on the next TFF report (the current one is 27 October). A yield decline of the sort the later article narrates would help the dollar leg and is not assumed; the article's narrative yields and its quote table disagree with each other, and neither is paired with an EURUSD print.

Falsifiers. EURUSD more than about 1 percent below the conditional entry while leveraged funds remain at a low percentile. A further SOFR reprice that lifts SR3U7 (4.535 on 3 November) and the real yield together. An equity/VIX confirmation of the sell-off. ECB path, once FST3 or a successor is actually in a packet, pricing a cut cycle the spot is merely tracking.

Realization. Half off on a +1.5 percent spot move from the conditional entry. The rest reviewed at two to six weeks, or when the next TFF report shows the leveraged-fund percentile off the floor. If that report is still at the floor and the spot has not moved, the squeeze has not started and the position should be smaller, not larger.

Sizing. USD notional $40m. USD per 1 percent: $400,000. Same SOFR funding math as CADNOK, about $44 a day. rv20 4.54.

Adverse path. A repeat of the 3-month -3.15 percent is about -$1.3m. The path is the safety bid the headline already describes, plus the missing spread around an ECB reference. Spot-linear. No options.

Exposures. Growth: EA activity is cooling, a negative for the long. Inflation: EA inflation temperature is warm and Bund yields are high in the 5-year window, so this is not a long-EUR-because-the-ECB-will-cut trade. Policy: euro futures unavailable; Fed path prices hikes, which the long is leaning against. Fiscal and term premium: the article's divided-government and shutdown talk is a US term-premium story and is unverified; the freeze already has the 10Y and 30Y at the 97th percentile, so some term premium is in the dollar. Energy: an oil decline would be a small EUR positive versus an oil-shock dollar, and it is not the reason for the trade. Currency-specific: the 1-year extreme and the TFF floor. Liquidity and positioning: TFF is the evidence; CME is down; report is eight days old, so the short may already have been cut or added to. Carry and funding: points unknown. With €STR at 2.445 and SOFR at 3.95, a long EURUSD is likely paying carry; the paper spot P&L does not include that cost, and I do not invent the points. Horizon: two to six weeks. Path: 5-day already +0.26 percent, so a small bounce is in the fix and the 1-day gave some of it back.

### AUDNZD — REJECTED

Long AUDNZD, which is Kevin's direction, is rejected. The relative test says the cross rallied because NZD fell, not because AUD was bid. The one month in which both rose versus the dollar, the cross fell. The cross does not track USDCAD and does not track the NOK complex. The 98.8 percentile is entry context for an NZD idea, and the NZD idea is the conditional long NZDUSD above, blocked on the curve. Buying the cross also buys an AUD leg that real money is already extremely short, at a spot that is not cheap (AUDUSD p5 76, 3-month -0.83 percent). De-escalation, if it is risk-on, is an AUDUSD question. Lower oil, if the article is right, is a terms-of-trade question and not a reason to pay up for AUD against NZD. The freeze headline is risk-off. Three regimes, none of which prices a long in this cross on the 3 November fixing.

Short AUDNZD, the mechanical fade of a z5 of +2.69, is also rejected. It would sell AUD, the leg that is not rich and the leg real money is crowded short, and buy NZD, the leg whose discount lines up with the weak NZ activity impulse. Kevin's undated nonresponse would be the only exhaustion argument for the short, and it has no date and no magnitude. The freeze's own latest day moved the cross lower because AUD lagged, which is the wrong leg for that story, while the 5-day and 3-month still show NZD weakness in force. Short AUDNZD is not cleaned up by calling it a CORRA hedge. The book does not need one, and the cross does not co-move with USDCAD anyway.

## Rejected alternatives

- Long AUDUSD on de-escalation. AUD is mid-pack. The crowded asset-manager short is real and is not a catalyst. The freeze headline is a risk-off tape. The article's lower oil is a terms-of-trade negative for a commodity currency. Copper's level, 6.3785, has no return, so there is no metals impulse to substitute for oil. Rejected.
- Short USDJPY. Level is high (158.29, p5 89) and the move has stopped (1-month +0.04 percent, 3-month +0.29 percent). JP-US 2Y at -271 bp is not a 5-year extreme (p5 71). BoJ held on the 30 October headline. TONA futures already price the hike path. Leveraged-fund JPY net is only -14,630 and sits at the 95th percentile, which means the speculative short has already been covered relative to the last year. Asset managers are long JPY at the 95th percentile. Fading the carry with unknown forward points, after the shorts have covered, into a still-wide rate gap, is not a trade. A post-election yield decline would be a new mark, and even then the yen cross has not been the live dislocation. Rejected on the freeze. Not promoted to conditional, because the article's yield quotes are not paired with a USDJPY and the freeze returns show no tension.
- Long USDCAD as an oil hedge of the CORRA receive. Not a mandate, and the cross is the wrong shape: USDCAD p5 is 83, so the dollar is the high side, and CAD has already rallied 1.95 percent over one month against a crowded leveraged-fund CAD short. Oil down might give some of that back. That is a guess about a beta, and CADNOK is the cleaner relative expression if the oil mark arrives. Rejected.
- Short NZDNOK or any fresh long-NOK expression. NZDNOK z5 -2.66 and NOKJPY z5 +2.31 are the trend. The freeze oil regime and the attack headlines still support NOK. Buying the 0th percentile because it is the 0th percentile is the mistake the extreme-is-not-a-thesis rule is there to stop. The 5-day NZDNOK return of -2.29 percent says the trend was alive into the fix. Rejected as a chase. The fade, if any, is CADNOK and only after oil is re-marked.
- Short GBPNZD. More extreme on the 1-year window than AUDNZD (p1 99.4, z1 +2.63, 5-day +2.02 percent, 3-month +4.16 percent) and the same NZD fact, plus a GBP leg with no sterling cash curve in the packet. GBPUSD itself is only p5 80. Asset managers are very short GBP (net -128,893, -50.8 percent of open interest, 3-year percentile 4.8), so fading GBPNZD sells a currency real money is crowded short. Rejected.
- Long EURGBP. Two-window extreme (p5 7.2, p1 0.2, z1 -2.91, 3-month -2.74 percent). The positioning extremes point opposite ways on the cross: leveraged funds are at the floor short EUR, and asset managers are extremely short GBP. BoE headlines cut both ways (a higher "new normal," and agents seeing no pay pass-through). No GBP curve. Rejected as an unresolved tug-of-war.
- Long EURCHF or long CHF. EURCHF p5 4.4 is a 5-year lowish print with a 1-year percentile of only 22. Leveraged funds are extremely short CHF (p1 0.96). There is no SNB path in the packet. A 5-year percentile without a 1-year extreme and without a policy leg is not enough. Rejected.
- Long NOKSEK as a cleaner oil-versus-non-oil fade. NOKSEK p5 93, z5 +1.52, 3-month +6.88 percent, which is the largest 3-month gain among the high percentiles. The 5-day return is already -0.48 percent. SEK has no cash curve and no TFF row. Sweden is outside the six-economy rate set. The conceptual cleanliness does not survive the missing policy, the missing positioning, and a 5-day turn that may already be the fade. Rejected.
- Fade AUDCAD. z5 +1.87 with p1 42 and negative 1-day, 5-day, 1-month, and 3-month returns. The rich 5-year level is already digesting. Rejected in both directions.
- Yen crosses as a group (AUDJPY p5 88 with a negative 3-month return and a 1-year percentile of 41, GBPJPY p5 90 with a flat 3-month, EURJPY 3-month -2.87 percent). They inherit the yen's structural cheapness and a rate gap that is wide and not, on the JP-US 2Y percentile, a fresh extreme. Recent returns are flat to negative. Rejected.
- Anything that needs an option, a forward roll, or a CME open-interest number. No surface, no points, CME unavailable.

## Ranked list

1. Long NZDUSD, $30m USD notional, $300k per 1 percent, 4–8 weeks, CONDITIONAL on the RBNZ curve and a post-election equity or VIX mark.
2. Long CADNOK, $40m USD-equivalent each leg, $400k per 1 percent, 2–6 weeks, CONDITIONAL on a same-timestamp oil markdown versus the frozen WTI 96.09 and Brent 103.60.
3. Long EURUSD, $40m USD notional, $400k per 1 percent, 2–6 weeks, CONDITIONAL on EURUSD still at or below 1.1179 and the safety bid not confirmed in equities or VIX.
4. Long AUDNZD, REJECTED. The cross is an NZD residual, not an AUD or oil or Canada-rates expression.
5. Short AUDNZD, REJECTED. The rich percentile is the NZD discount, the crowded TFF short is AUD, and the jobs nonresponse is undated.
6. Short USDJPY, REJECTED. High level, stalled returns, hike path already in TONA futures, speculative yen short already covered on the 27 October TFF.

No probabilities are attached. None of the six is READY on the 3 November spots. Sketches are alternatives. Funding is SOFR on the 1 percent risk unit. Forward points, bid/ask, and swap carry are missing on all of them.
