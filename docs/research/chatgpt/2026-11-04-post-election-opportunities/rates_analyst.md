# Rates and relative value — cycle 2026-11-04

Written 2026-11-05 during this execution. Evidence cycle name remains 2026-11-04. It is impossible to reconstruct a blind Nov 4 forecast: this note is retrospective, written after the freeze, after the authorized CNBC body, and after the prior CORRA expression note. It does not backdate a morning call.

Analyst: Grok 4.7 rates and relative value, research only. ChatGPT keeps the investment decision. This file does not approve, resize, or remark any book.

## Pins

| Object | Value |
|---|---|
| Commit | `612666a21e621e6bb437802cb48ace011f181b7b` |
| Review | `overnight-20261104` / `review-001`, status accepted |
| Stated cutoff | `2026-11-04T05:35:22.541505-05:00` |
| Packet SHA-256 | `d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f` |
| Market-state digest | `a4a28373c5db64e71f860f73ba0267502bcba92bf32fe09f32ca300068ce2ae9` |
| Market-state `generated_at` | `2026-11-04T10:52:31Z` |

The stated cutoff is 10:35:22Z. The assigned market state was generated at 10:52:31Z. Both clocks stand. Contract timestamps inside the snapshot are earlier than both: CORRA and SOFR fixings 2026-11-02, SR3 and sovereign par yields mostly 2026-11-03, AONIA benchmark dated 03-Nov-2026, TONA cash 2026-10-30, Australia par yields 2026-10-28.

The stored book mark stays 3.16 as of `2026-11-03T14:35:29Z`. Arithmetic below does not replace it.

Prior research at `250bf6f4a6d00e1f115fc6305d0a998a632f9651` (`docs/research/chatgpt/2026-11-04-corra-expression-review.md` and the calculator under `docs/research/chatgpt/2026-11-04-corra-expression/`) is an artifact to challenge. It is not new market evidence and ChatGPT did not approve it. ChatGPT did not approve dropping March/June and halving risk into September/December.

The trader room was not tallied and is not treated as fact.

## Frozen observations

### Sovereign par yields

US, 2026-11-03. 2Y 4.61, 5Y 4.74, 10Y 4.95, 30Y 5.32. One-day changes were higher: 2Y +2bp, 5Y/10Y/30Y +4bp. One-month changes were a rally: 2Y −22, 5Y −32, 10Y −33, 30Y −31. Five-year percentiles: 2Y 79th, 5Y 96th, 10Y 97th, 30Y 98th. One-year percentiles sit in the mid-80s for all four. 2s10s is 34bp (1y percentile 12th, z −1.27; 5y percentile 61st). 5s10s is 21bp (1y percentile 11th, 5y percentile 62nd). The curve is flat against the last year and ordinary against five years. The one-month rally was larger in the belly and long end than in the 2Y, so 2s10s flattened 11bp over the month, then steepened 5bp over five days.

Canada, 2026-11-02. 2Y 3.26, 5Y 3.46, 10Y 3.74, long 4.06. One-month: 2Y −1bp, 5Y −16, 10Y −20, long −22. The Canada front end did not join the US 2Y rally. 2s10s is 48bp (1y percentile 2nd, z −2.42; 5y percentile 63rd). Cross-country spreads in the snapshot are dated on the older leg. CA−US 2Y is −133bp as of 2026-11-02 (1y percentile 23rd, 5y percentile 10th, 1m +18bp). CA−US 10Y is −117bp (1y percentile 8th, 5y percentile 10th). Those spreads are not the Nov 3 US yield minus the Nov 2 Canada yield.

Australia, 2026-10-28, age 7 days. 2Y 4.951, 5Y 4.946, 10Y 5.208. 2s10s is 25.7bp (1y percentile 0.6, 5y percentile 9th). AU−US spreads in the snapshot are as of 2026-10-28 (2Y +28bp) and are not a mix with the Nov 3 US close.

Euro area, 2026-11-03. 2Y 3.05, 5Y 3.12, 10Y 3.31, 30Y 3.68. 2s10s 26bp, 1y percentile 3rd. Japan, 2026-11-02. 2Y 1.88, 5Y 2.243, 10Y 2.817, 30Y 3.94. 2s10s 93.7bp, 5y percentile 85th. New Zealand sovereign yields are unavailable (official B2 blocked; no vendor substitute). NZ sovereign admission in the permission block is research-only.

### Real yield and breakeven, unsynchronized

FRED DFII10 is 2.62% on 2026-11-02. FRED T10YIE is 2.30% on 2026-11-03. The snapshot stores both in basis-point units (262 and 230). The Nov 3 nominal 10Y is 4.95. Subtracting the Nov 2 real from the Nov 3 nominal leaves 2.33, three basis points from the Nov 3 breakeven. That gap is a vintage mismatch. These three numbers are not a decomposition of one price. No percentile is stored on either series. Any split of the 4.95 into expected inflation and real yield remains a hypothesis except for the two raw prints on their own dates.

### Policy paths that can actually be traded

Supported futures in this snapshot: CME SR3 SOFR, Montréal Exchange CRA CORRA, ASX 30-day interbank AONIA, OSE 3-month TONA. Eurex FST3 €STR futures are unavailable. No TY, US, WN, or other Treasury-futures settlement is in the snapshot. CFTC names the 2Y, 5Y, 10Y note and Treasury bond markets; that is positioning, not a mark. Official government zero curves are a paper proxy, explicitly not executable, and they are older than the par yields (US 2026-10-30, Canada 2026-10-14, Australia 2026-09-30, ECB spots 2026-11-02, Japan par yields identical to the benchmark par set on 2026-11-02).

SOFR cash 3.95 on 2026-11-02 (NY Fed). SR3 on 2026-11-03: Z6 4.16, H7 4.365, M7 4.495, U7 4.535, Z7 4.515, then a slow ease to 4.415 by Sep/Dec 2029 and a later rise toward 5.08 by Mar 2036 in contracts whose open interest goes to zero. From cash to the U7 peak is +58.5bp. From Z6 to U7 is +37.5bp. From the peak to the 2029 trough is −12bp. The hike is front-loaded into the first half of 2027; the reds are almost flat; the far rise is a long-horizon nominal, not the next few meetings. One-month SOFR (delayed ICE via eSignal, not the tradable SR3 book) is consistent with that shape: Nov 3.8975 (through the fixing), Dec 4.045, Jan 4.115, Feb 4.165, Mar 4.235, and a peak near 4.51 in autumn 2027. Open interest on SR3Z6 is 1.67 million, volume 294 thousand; Z7 open interest is 1.54 million. SR3 is the executable US rates leg.

CORRA cash 2.54 on 2026-11-02. One-month contracts stop in February 2027: Nov 2.515, Dec 2.605, Jan 2.655, Feb 2.785. Three-month: Z6 2.75, H7 2.970, M7 3.115, U7 3.225, Z7 3.310, H8 3.385, M8 3.430, U8 3.465, Z8 3.475, then a slight ease. H/M/U/Z 2027 average 3.155, which is +61.5bp over cash. Premia over cash: H +43.0, M +57.5, U +68.5, Z +77.0. Z minus H is 34bp. The path is still rising through December 2028. CRA open interest and volume are null on every listed contract. The strip is paper-markable. Exchange depth is not evidenced. A bigger futures-minus-cash premium is the priced path. It is not a measure of cheapness.

AONIA cash 4.60 dated 03-Nov-2026. Contracts are monthly. Nov26 4.82 (open interest 25,654, volume 14,536), then a rise to Mar27 4.915 (open interest 400) and an ease to Apr28 4.605 (open interest null). December 2027 is 4.71, +11bp over cash. Depth is real in the front month and absent in the back. €STR cash is 2.445 on 2026-11-03, with no futures. TONA cash is 1.227 on 2026-10-30. The OSE path is a steady hike: Dec26 1.45, Mar27 1.6625, Sep27 1.945, Dec27 2.05, Jun31 2.655. The snapshot states that TONA futures settle on 3-month compounded confirmed TONA, Act/365, not the raw overnight print. No TONA basis-point value is in the snapshot. Open interest is null.

Snapshot cross-market outrights, same expiry label, 2026-11-03: SOFR minus CORRA is 141bp (Z6), 139.5 (H7), 138 (M7), 131 (U7), 120.5 (Z7), 110 (H8), 96.5 (Z8). Cash SOFR minus cash CORRA is 141bp, so the front spread matches the cash spread and the forward spread narrows about 44bp by end-2028. SOFR minus the single AONIA month of the same label is −55bp in Mar27 and −19.5bp in Dec27. That label match is not a matched accrual window. AONIA is monthly. CORRA and SOFR are quarterly.

### What the macro and oil complex say on the freeze

US core PCE carried in the temperature block is 3.0478 for 2026-07, the 3-month annualized Core PCE transform against a 2% anchor (calibration v1). Retrieval is 2026-09-21. The series is `source_failed` / previous release retained. Inflation level 63, impulse −0.81, classified warm. Labor for 2026-09, retrieved 2026-10-06: unemployment 4.2, wages 3.02 year-over-year, payrolls transform 70.7 (3-month context, not a percent). Labor level 51, cooling. GDP domestic demand is the carried 2026-Q2 print at 1.8. October manufacturing survey 54.9 was retrieved on the freeze morning. The Fed-hold and “talks tough” headlines are in the 24-item set as headline-only CNBC metadata from 2026-10-28. The hike path is the market’s path after a hold, not a hike that has just been delivered.

Canada, 2026-09, inflation retrieved 2026-10-20 with release date 2026-10-19. Headline CPI 3.0928 year-over-year. Underlying 1.85 is the equal average of CPI-trim and CPI-median year-over-year against a 2% anchor. Labor, retrieved 2026-10-15: unemployment 6.5 against a 6.0 anchor; employment −11.6 is the three-month mean change in thousands against a +25k trend; wages 2.34 year-over-year against a 3.0 anchor, with a positive impulse on a cool level. Labor dimension 41, cooling. The PRiMA proxy’s CORRA-versus-midpoint input uses a 2.75 midpoint and a −21bp gap. That midpoint is a proxy rule parameter. It is not a documented Bank of Canada neutral estimate, and the proxy note says CORRA is not a Governing Council vote. The book and the open hypothesis assert a late-October Bank of Canada hike. This freeze’s news file does not contain that decision. The prior expression note already listed the decision record as a missing ingest. The hike stays an unverified assertion inside ChatGPT’s own text.

Australia inflation, 2026-09, retrieved 2026-10-28: headline 4.3 year-over-year, trimmed mean 3.6 against the 2.5 midpoint of the 2–3% band. Labor unemployment 4.72, employment three-month mean negative. Euro area inflation is a new observation for 2026-10: headline 4.0, underlying 2.6, both warming. Japan, 2026-09: headline and underlying both 2.2; wages 3.9 in August; unemployment 2.4. The BOJ-hold headline is headline-only. New Zealand labor in the temperature block is still 2026-Q2 (unemployment 5.6). No post-freeze jobs release is in the packet.

Oil, Yahoo, 2026-11-03: WTI 96.09, Brent 103.60. These are the frozen marks. PRiMA shock-persistence contracts: Brent Dec26 117.64 on 2026-10-30, +19.61 dollars / +20.0% over one month; Brent Dec27 84.88 on 2026-11-03, +3.6%; Brent Dec28 77.38, +2.7%. Versus the July 2026 MPR conditioning assumption of 70, Dec27 is +14.88. The proxy’s own label is `parallel_upward_repricing`, direction STABLE, strength low, confidence high. The contract math is a front-loaded jump, not a parallel move along the curve. Direct energy IPPI +12.1% month-on-month in September is shadow and is not in the score. Scored channels: consumer-price breadth RISING (5 of 8 CPI majors positive), raw-material prices ex crude energy FALLING, IPPI ex energy STABLE at +0.28% month-on-month, shock persistence RISING. Net proxy direction remains STABLE.

CFTC TFF futures-only, report date 2026-10-27, age 8 days. Asset-manager net in the 10Y note is +51.0% of open interest, 99th percentile of one year and of three years (z 1y +1.73). Asset-manager net in the Treasury bond is +20.3% of open interest, 1st percentile of one year (z −1.77): an unusually small long, not a crowded one. Leveraged-fund net in the 2Y is −30.0% of open interest with a 3y percentile of 94 and z +2.0, so that short is smaller than the fund’s own three-year distribution. CME daily positioning is unavailable. Percentiles are in-sample descriptions of this history. They are not a strategy backtest. Analog rows inside the yield objects are nearest one-month-move neighbors, not an out-of-sample test.

Funding. Official SOFR 3.95, ACT/360, observation date 2026-11-02, is the zero-return benchmark. A flat book has zero net financing. The residual charges SOFR on 2.5 million of shocked-risk capital. SR3 is forward context only and is not the accrual rate.

### The freeze headline, still inside the cutoff

`news:2781b15c74e39a97`, CNBC, published `2026-11-04T04:02:00-05:00`, before the 05:35:22−05:00 cutoff. Headline: “Treasury yields fall as investors crowd into bonds for safety amid election stock sell-off.” Summary in the packet: “Headline-only public metadata; article body was not retrieved.” Salience score 11, the lowest of the 24. Transmission disposition `assess`, reason `usd_rates_repricing`. The URL is the same URL as the later article. The early object is a safety-bid and stock-selloff headline. It does not contain the later yield quotes, the oil moves, the seat counts, or the deficit commentary. Nov 3 Treasury marks were up on the day, so this headline is not inside the frozen yields.

## Later authorized CNBC

Same URL, `https://www.cnbc.com/2026/11/03/treasury-yields-fall-as-democrats-win-big-in-us-midterm-elections.html`. Source updated `2026-11-04T17:11:00Z`. Retrieved cache 18:01Z. Received later in the Nov 4 Work conversation, after the freeze. The exact conversational receipt minute was not captured. Full later facts were not available to the other traders. The authorized instruction is that the 12-item compact PM news view omitted the early headline; this snapshot stores the headline inside the 24-item set and does not store a separate 12-row object.

Treat the body as CNBC reporting, not primary-source verified.

- Democrats obtained majorities in both the House and the Senate, flipping Senate seats in Iowa, Kansas, North Carolina, Ohio, South Carolina, Maine, and Texas, and won key gubernatorial races in Ohio and Texas.
- Narrative quotes: 10Y 4.898% down more than 5bp, 30Y 5.293% down more than 3bp, 2Y 4.573% down more than 4bp. An embedded quote table differed: 2Y 4.577 and 30Y 5.29. These are not fused with each other or with the frozen 4.61 / 4.95 / 5.32 marks. The reference close for “down more than” is not identified here. Rough consistency with a small rally from the Nov 3 close is not a new mark.
- WTI fell about 8% toward $88. Brent fell about 8% toward $94. Frozen Yahoo closes remain 96.09 and 103.60. The gaps are about eight and ten dollars. They are not synchronized prices.
- JPMorgan traders focused on reduced deficit spending through congressional budget constraints, potentially involving a shutdown. BondBloxx interpreted divided government as potentially limiting deficit growth and saw no immediate move toward Iran escalation. These are attributed interpretations, not established fiscal or geopolitical outcomes.
- JD Vance blamed the Iran war for Republican losses. The article links lower oil to post-election developments. Causal attribution is a hypothesis.

The early headline and the later body are different stories. The early story is a safety bid during an equity selloff, with no body and no yield level. The later story is an election result, lower oil, a small and internally inconsistent yield quote, and a deficit-constraint interpretation. A trade that needs the later prices is conditional on an exact common mark. Nothing in this section rewrites the Nov 3 curve.

## Kevin

Post-freeze, not verified data, and not an instruction. AUDNZD in the freeze is 1.2417 on 2026-11-03, 5y percentile 99th, z 2.69. The level is near a five-year high on the frozen history. Kevin’s claim that it failed to rally on a dismal New Zealand jobs print has no release date, magnitude, or intraday series in the material provided. No release is invented here and no event study is claimed. The temperature block’s New Zealand unemployment is still the 2026-Q2 print at 5.6.

His scenario: de-escalation is the main plausible source of current risk-on, potentially lifting AUDNZD while Canadian rates fall; escalation may raise Canadian rates while hitting risk assets and AUD. The freeze’s oil and Hormuz headlines point the other way (mines, a thin buffer, shipping risk). De-escalation is his scenario and, separately, a hypothesis one can hang on the later article. It is not the frozen state.

Canada rates are their own exposure. A negative correlation with AUD in an escalation is a joint-stress fact, not a reason to badge a CORRA receive as a hedge of AUDNZD, and not a reason to keep a receive in order to finance an FX view. A positive correlation between a Canada receive and a US front-end receive in an oil-down scenario is a sizing constraint on the sum of DV01, not a veto on either leg. The legs differ in accrual, local inflation, terms of trade, and depth.

## Deterministic comparisons

These are identities on the frozen marks. They are not fair values. Lot math below uses the snapshot’s own contract notes and FX. It agrees with the prior research figure of 349 CRA lots per expiry. It is not a rerun of `calc_contracts.py`, and the prior scenario dollars are cited as prior research only.

**Paper DV01 versus futures face.** The book’s 250 million notional, shocked 100bp, is 2.5 million of risk capital, about 25,000 USD per bp. That is the legacy duration-one identity on 250 million. It is not 250 CRA contracts. CRA basis-point value is CAD 25 per 0.01 index point on a CAD 1,000,000 face (CAD 1,000,000 × 0.01% × 90/360). Snapshot FX is USDCAD 1.3975310850702212 on 2026-11-03, and the analytics field `fx_usd_per_unit` for CAD is 0.7155475900915316. USD per CRA basis point = 25 × 0.7155475900915316 = 17.8887. Lots that reproduce 25,000 USD per bp = 1,397.5 total, or 349.38 per expiry across four equal expiries. 349 lots × 17.8887 = 6,243 USD per bp per expiry. Four expiries ≈ 24,973 USD per bp. Two expiries at 349 lots ≈ 12,486 USD per bp, which is half the strip. Half the stress loss is the arithmetic of half the DV01. It is not evidence that the surviving legs are the better trade. SR3 is USD 25 per bp per lot. 200 SR3 lots are 5,000 USD per bp. 400 SR3 lots are 10,000 USD per bp.

**Matched SOFR versus CORRA, quarterly labels.** Own-cash premia on the equal-weight H/M/U/Z 2027 strips: Canada +61.5bp, US +52.75bp, gap 8.75bp. The calendar from Z6 to Z7 is +56.0bp in CORRA (2.75 to 3.31) and +35.5bp in SOFR (4.16 to 4.515). Canada prices 20.5bp more steepening over that year. From Z6 to Z8 the SOFR−CORRA spread falls from 141bp to 96.5bp. US peaks at U7 and is 2bp lower by Z7. Canada is still rising at Z7 and keeps rising into 2028.

**AONIA quarterly labels, approximate, not IMM-matched.** Mean of Mar/Apr/May 2027 = 4.908 (+30.8bp over cash). Jun/Jul/Aug = 4.855 (+25.5). Sep/Oct/Nov = 4.773 (+17.3). Dec27/Jan28/Feb28 = 4.687 (+8.7). The single-month snapshot spreads (SOFR minus AONIA = −55bp in Mar27) use one monthly print against a quarterly futures label. A three-month average against SR3H7 at 4.365 is about +54bp, close to the label spread only because Mar/Apr/May happen to sit on top of each other. That closeness is not a license to treat Dec27 AONIA (4.71) and CRAZ27 (3.31) as the same accrual. Day-count basis-point values also differ: ASX publishes A$24.66 per 0.01 on a fixed 30/365 and a A$3,000,000 face. AUDUSD in the snapshot is 0.6983819578934215, so one AONIA basis point is about 17.22 USD. That conversion is a sketch for paper sizing, not a hedge ratio.

**Unchanged-tenor roll, prior research, not re-derived here.** The prior note’s one-quarter unchanged-tenor slide is about +14bp on the equal-weight CORRA receive, about 350,000 USD at the 25,000 USD/bp paper DV01, and about −13.5bp of leg DV01 for pay H / receive Z. Those signs are assumption-dependent. They are what the curve pays if the path one is disagreeing with stays in place. They are not a base-case edge. This pass does not use them to rank a reshape over a close.

**Treasury versus SR3, rough and not a fitted par.** The simple average of the first eight SR3 contracts (Z6 through U8) is 4.434. The Nov 3 2Y par is 4.61, about 18bp higher. The simple average of CRA Z6 through U8 is 3.206. The Nov 2 Canada 2Y is 3.26, about 5bp higher. A positive bond-versus-futures gap of that size is a basis, a coupon effect, and a date mismatch. It is not a cheapness signal. 10s30s on Nov 3 par yields is 37bp (5.32 − 4.95). No 10s30s history is stored, so no percentile is claimed. US official 10Y zero on 2026-10-30 is 4.9324 against the Nov 3 par of 4.95. Too close, and too stale, to support a curve-proxy trade against SR3.

## Judgment

### 1. US rates: fiscal and term premium versus the policy path

Two stories are in play, and they do not combine.

On the freeze, the policy path is a hike cycle of about 58bp from 3.95% SOFR to SR3U7 at 4.535, mostly by June 2027, then a 12bp ease into 2029. The cash curve is still high versus five years after a 22–33bp rally in the last month, and yields rose 2–4bp on Nov 3 itself. Core PCE evidence is a July 3-month annualized rate near 3.05, carried since September 21. The Fed-hold headlines say the committee stood still and the chair talked tough. High oil in the freeze (WTI 96, Brent 104, front Brent contract 118 at the end of October) is consistent with that hike path. It does not say the path is too low or too high by a margin that survives a missing August–October PCE print. Percentile richness of the 10Y and 30Y is the level, not a discount. Asset managers are crowded long the 10Y note as of October 27 and unusually light the bond. There is no bond-futures price to express the relative, and the cash 30Y is as rich on its own five-year percentile as the 10Y. A 2s10s steepener fights a path that prices hikes and sits at an ordinary five-year percentile. A pay of the SR3 peak requires a third hike beyond the 58bp already in U7. The freeze does not show it.

The early headline is a safety bid and an equity selloff. The body was not retrieved. The Nov 3 marks do not contain it. Positioning that is already max-long the 10Y note is a poor place to add a safety receive on a headline.

The later article is the other story. The reported yield move is a few basis points, larger in the narrative 10Y than in the narrative 30Y, with a table that does not match the narrative to the tenth. That pattern is not a long-end-led term-premium rally. JPMorgan’s deficit-constraint reading and BondBloxx’s divided-government reading are attributions. Divided government is not, by itself, a lower deficit. A shutdown, if one occurs, is a funding and growth event that has not been established. Oil down toward 88/94, if it were a real and sustained common mark, would be an inflation and reaction-function shock. It would hit breakevens first and the SR3 whites second. It can raise real yields if the channel is de-escalation and risk-on, or lower them if the channel is a growth scare. The freeze real and breakeven cannot settle that, and the article does not quote them.

What should outperform if the later story is oil, and only then: the front policy curve, not the 30Y. What is still attractive after the reported rally: nothing outright, because the rally is not a mark and the freeze entry was already after a 30bp month. The 30Y did not cheapen relative to the 10Y by a gap this packet can measure. Chasing the narrative 4.898 or paying the narrative 5.293 would fuse an article quote with a frozen curve.

**Candidate kept — CONDITIONAL.** Receive SR3 whites (Z6, H7, M7, U7), about 200 lots total, 5,000 USD per bp, horizon through the next two US inflation prints and the following FOMC, only if all of the following common inputs exist together:

1. SR3 settlements for Z6, H7, M7, U7, Z7 on one post-article session.
2. NY Fed SOFR for that session’s latest fixing.
3. Same-session DFII10 and T10YIE.
4. Same-session nominal 2Y and 10Y.
5. A WTI and Brent close from the same source family as the freeze (Yahoo futures or an exchange settlement), not the article’s “toward $88 / $94”.

Rule, not an order: the receive is eligible only if the cash-to-U7 hike is still near 58bp and T10YIE is meaningfully below the frozen 2.30 while DFII10 is not the leg that rallied. If the whites have already repriced, there is no trade. If breakevens did not fall, the oil channel did not reach inflation pricing and the receive is rejected. If only reals fell, this is not the oil expression. Missing probabilities stay missing. No fair value is stated.

Falsifier after entry: oil reverses to the frozen mid-90s/100s, or a new core PCE 3-month annualized rate holds near 3 with Fed communication that defends the hike path. Realization: take the receive off if U7 drops 15bp versus the new entry without a matching move in the 2029 trough, or if breakevens snap back. Adverse path: de-escalation lifts real yields and the nominal front sells off; 200 lots lose 5,000 USD per bp. Do not add the 10Y note on top of it. The October 27 asset-manager long is the crowding fact, and a 10Y receive doubles the nominal beta the conditional is trying to isolate in the whites.

**Rejected US expressions.** Outright 10Y or 30Y receive for a fiscal, shutdown, or safety-bid story. 2s10s or 5s10s steepener. 10s30s steepener. Pay SR3U7 as “not enough hikes.” Any TY/US/WN futures package. Official-curve forward-forward versus SR3. Far SR3 (2032–36) as a term-premium short: open interest dies, and there is no decomposition.

### 2. Cross-country

Canada at the freeze prices a longer hike than the US: +61.5bp over cash on the 2027 strip versus +52.8bp in the US, and +56bp of Z6–Z7 steepening versus +35.5bp. The domestic case against that path is real: trim/median 1.85, unemployment 6.5, employment three-month mean negative, wages 2.34. The domestic case for the path is also real: headline CPI 3.09, rising CPI-major breadth, September energy prices in the shadow layer, Brent Dec27 still 15 dollars over the July MPR’s 70, and a proxy that is STABLE rather than easing. The Canada 2Y fell 1bp in a month while the US 2Y fell 22bp. The labor and trim prints have been in the packet since mid-October. The path did not bend. That is what the price requires: the market has looked at the slack and has kept the hikes. Fading it needs a new piece of information, which the freeze does not have. Paying it needs oil to keep propagating, which the backwardation (front +20% in a month, Dec27 +3.6%) only partly supports, and PRiMA’s net vote is already STABLE. Neither side clears a from-flat hurdle on frozen marks.

A DV01-matched pay of SR3 against a CORRA receive is a separate position, not a hedge label. On a common 20bp selloff it is roughly flat by construction, so it spends the Canada level if the Canada level was the trade. On a Canada-only move it keeps the local residual and imports US inflation risk that this freeze cannot carry: core PCE is July. The 8.75bp own-cash gap and the 20.5bp extra Z6–Z7 steepening are small next to a 15 dollar oil wedge over the MPR assumption. They can be the oil basis. They are not a demonstrated mispricing. Rejected as a freeze trade, both as a hedge of the residual and as a standalone.

Australia is the cleanest local policy disagreement and it fails on marks. Trimmed mean 3.6 and headline 4.3 sit with a futures path that hikes about 30bp into March 2027 and gives the hike back by early 2028 (Dec27/Jan/Feb average 4.687, +9bp over cash). The give-back is the statement that any RBA hike is temporary. The open-interest for that statement is null after mid-2027. March open interest is 400 lots. Settlements without volume are not a demonstrated two-way price. The front hike itself, about one 25bp move, is plausible against 3.6% trimmed mean and is not the disagreement. Paying null-open-interest 2028 months against March would be the expression, and it is rejected until there is volume or a second source in those months. Monthly versus quarterly accrual and the A$24.66 versus USD 25 basis-point values would still have to be matched before any SOFR or CORRA cross. Frozen high oil is friendly to “the RBA does not give the hike back”; the later article’s lower oil would be hostile to that pay. The article therefore does not rescue the AONIA calendar. It is an additional reason to leave it alone.

Japan’s TONA path is a smooth hike of about 80bp by December 2027 from a 1.227 cash rate, with inflation at 2.2 and wages at 3.9 after a hold. No kink is large enough to isolate. No contract DV01 is in the snapshot, so a lot size would be invented. Rejected. Euro area HICP at 4.0 and underlying at 2.6 in October argue against a global cutting cycle, and FST3 is unavailable, so there is no policy expression. The cash 2s10s at the 3rd one-year percentile is a curve fact without a futures leg. Rejected. New Zealand rates are unavailable. Rejected. No NZ cash leg is smuggled in through Kevin’s jobs comment.

**Candidate kept — CONDITIONAL.** A new equal-weight receive of CORRA H/M/U/Z 2027, not the September/December reshape, only as a fresh trade. Size if triggered: about 150 lots per expiry, roughly 2,700 USD per bp per leg and 10,700 USD per bp in total, using the snapshot FX identity above and labeled provisional. Horizon: one to three months of repricing, not the December 2027 fixing, which has not started.

Exact marks required, one common session:

1. CRAH27, CRAM27, CRAU27, CRAZ27 settlements and, if published, open interest and volume.
2. CORRA fixing.
3. Brent and WTI closes from the freeze’s source family.
4. Confirmation that no Bank of Canada statement in that session validates a 2027 path in the mid-3s. The late-October decision record is still a missing ingest; a new expression should not rest on the hypothesis text.

Rule: eligible only if the four-contract average is still within about 5bp of 3.155 and Brent has actually printed in the low-to-mid 90s rather than the article’s round “toward $94”. If the strip has already rallied, the conditional is dead. If oil has not fallen, the freeze rejection stands. Causal driver would then be an oil and energy-CPI markdown against a path that had been unchanged. Transmission is the Bank of Canada reaction function, not AUDNZD. Falsifier: underlying inflation or wages reaccelerate, employment turns up through the +25k three-month trend, or the path sells off toward 3.35–3.40. Realization: cover if the average drops 15bp from the new entry, or if Brent reclaims the frozen 100s. Adverse path: the oil drop is a growth scare that hits CAD assets and the Bank still hikes because headline stickiness dominates; 10,700 USD per bp of loss, and a simultaneous SR3 receive would add the same sign. If both conditionals were live, cap the sum near 10,000 USD per bp and prefer the Canada receive when the TIPS split is ambiguous, because Canada is the terms-of-trade and energy-CPI leg. Prefer the SR3 receive only when the US breakeven rule above has fired and the Canada strip has already moved. Do not run both at the old 25,000 USD per bp.

The regimes where the apparent oil hedge fails: an oil drop that is a demand collapse (Canada rates receive works, AUD and risk assets do not), and an oil drop that is de-escalation with a hotter US core (breakevens fall less than reals rise, so the US nominal receive loses while Canada still rallies). Those are reasons to keep the legs separate and small, not reasons to force a factor-neutral book.

### 3. The existing position

`pm-chatgpt-595561a1b90f`. Long the equal-weight CORRA 2027 H/M/U/Z paper strip. Notional 250 million after the 2026-11-03 reduce from 500 million. Entry 3.40 on 2026-09-20. Book mark 3.16 as of `2026-11-03T14:35:29Z`, from the earlier packet. This freeze’s H/M/U/Z implied rates are 2.970 / 3.115 / 3.225 / 3.310. Their average is 3.155. The 0.5bp gap versus the stored 3.16 is about 12,500 USD at the stated 25,000 USD per bp. The book is not remarked. Stored economics, unchanged: unrealized 600,000, realized 600,000, funding cost 24,555.56, risk capital 2,500,000 on a 100bp shock. Side `long` on the strip average means receive. Paper round-turn commission is not evidenced. CRA depth is null, so there is also no evidenced exchange franchise being warehoused.

The stored invalidation is a reacceleration of underlying inflation, labor, and wages, plus Bank of Canada guidance that validates the path, or a strip cheapening back toward 3.35–3.40 with that confirmation. This freeze does not fire that invalidation. An unfired invalidation is a stop that has not been hit. It is not a reason to keep a position. Prior profit from 3.40 to 3.16 is the move that already happened. The open hypothesis still calls the strip an overpricing candidate at a reduced size. That is ChatGPT’s prior text, updated 2026-11-03, not a fresh edge.

From flat, on permitted evidence, I would not initiate the residual. The 61.5bp premium is the hike path. Slack and a 1.85 trim/median average are the best argument, and they have not moved the Canada 2Y or the futures path, which still rises through 2028. Headline inflation, breadth, and Brent at 15 dollars over the July MPR assumption are the opposition, and PRiMA is STABLE. Null open interest means the paper mark is the only mark. The later oil article would weaken the opposition only after a new Brent close and a new CRA strip. It is not a reason to sit through it in a position that fails the freeze test. Existing ownership does not change the test. The friction difference versus a futures account is real and small: no evidenced commission, and no evidenced CRA market to exit either. Closing a paper strip does not pay a ticket this packet can point to.

**Action: CLOSE** the residual. Do not add. Do not reduce into September/December. Do not convert it into pay March / receive December. Do not overlay a DV01-matched SR3 pay as the exit. The close is a rates judgment at frozen marks. If the integrator executes after the article, the fill needs a new common strip mid; do not fill at the stale 3.16 as if it were still the market. A new mid that is lower (richer) makes the close more consistent with the from-flat test. A new mid that is back near 3.35–3.40 is a different trade and is not authorized by this close.

The prior reshape fails the same test. Keeping U and Z at 349 lots because their premia over cash are +68.5 and +77 is the cheapness error: those are the largest hikes on the strip, and the curve keeps rising after Z7. Dropping March and June because “the front can be validated” concentrates the receive in the sector a further near-term hike does not mark, and it cuts DV01 in half, which lowers the stress loss by arithmetic. The prior note’s own strongest objection is the right one: labor and the 1.85 average are arguments about the whole path. Roll that is positive only if the tenor curve is unchanged is the carry of the path being faded. ChatGPT has not approved that reshape. I reject it.

Screened and rejected without a line of their own beyond the list below: EA policy (no futures), TONA outright (smooth path, no DV01), NZ rates (unavailable), Treasury futures (no marks), official-curve flies (stale proxies), US curve steepeners, pay-the-peak SR3, AONIA 2028 give-back, and the SOFR-versus-CORRA package at frozen marks.

No probabilities are assigned. No fair value is estimated. Embedded percentiles, z-scores, and move analogs are descriptions inside this snapshot.

## Ranked list

1. CLOSE `pm-chatgpt-595561a1b90f` CORRA_2027H-Z equal-weight receive, 250m paper, about 25,000 USD/bp; exit on the next common CRA strip mid, not the stored 3.16; horizon immediate; READY on the freeze.
2. CONDITIONAL new receive, equal-weight CRAH27/CRAM27/CRAU27/CRAZ27, about 150 lots per expiry (about 10,700 USD/bp total, provisional); horizon 1–3 months; only if the strip is still within about 5bp of 3.155 and Brent has printed in the low-to-mid 90s on a freeze-family close.
3. CONDITIONAL receive SR3Z6/H7/M7/U7, about 200 lots total (5,000 USD/bp); horizon through the next two US inflation prints; only if the cash-to-U7 hike is still near 58bp and same-session breakevens fell without a matching real-yield rally.
4. REJECT reshape to CRAU27 and CRAZ27 at 349 lots each (about 12,500 USD/bp); that half-DV01 is not a better expression; ChatGPT has not approved it.
5. REJECT pay CRAH27 / receive CRAZ27; the prior one-quarter unchanged-tenor roll is a loss of about 13.5bp of leg DV01, and the 34bp H–Z spread is the path, not carry.
6. REJECT outright US 10Y or 30Y receive for the safety-bid headline or the attributed deficit constraint; no supported bond futures; after the reported rally the long end is not the leg that led.
7. REJECT pay AONIA 2028 months versus receive Mar27; the disagreement sits in null-open-interest months, and the later oil story is hostile to that pay.
8. REJECT DV01-matched pay SR3 versus receive CRA, as a hedge of the residual and as a freeze standalone; the extra Canada steepening can be the oil wedge, and US core PCE is still July.
