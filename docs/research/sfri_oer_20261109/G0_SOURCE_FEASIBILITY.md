# G0 source and vintage feasibility

Audit date: 2026-11-10. Research information cutoff: 2026-11-09. Parent review: Grok 4.7. This note decides whether a direct CoreLogic/Cotality Single-Family Rent Index test can be run. It does not report proxy forecast errors.

## Verdict

The direct SFRI versus CPI owners' equivalent rent test is **blocked**. Cotality sells the national index as a licensed file. No public machine-readable history was found. Press releases quote scattered year-over-year headlines, state that the index is fully revised at every release, and in the latest pre-cutoff release contradict themselves. Those pages are not a historical SFRI sample. Zillow ZORI and S&P CoreLogic Case-Shiller are different series and are not substitutes.

## Series identity

The approved question names Cotality's Single-Family Rent Index, formerly published by CoreLogic. The product page describes a repeat-rent index for single-family rentals, at national and CBSA level, delivered as a flat file or through cloud and REAS platforms, with sales contact required. It is not the Cotality home-price index and not the S&P CoreLogic Case-Shiller index.

Press methodology, repeated across releases, says the index applies a repeat-pairing method to MLS rental listings of attached homes, detached homes, and condominiums, and that the indices are fully revised with each release. That revision sentence rules out splicing successive headlines into a real-time series even when the prose is internally consistent.

Official page checked: https://www.cotality.com/products/single-family-rent-index (page metadata dateModified 2026-10-23). The page says updates arrive about three weeks after month-end. That sentence describes the commercial product. It is not evidence that a public series exists on that lag.

FRED was not usable from this environment (download timed out). A public FRED page for SFRI was not identified in search. No SFRI observations were taken from FRED.

## What Warren Pies actually wrote

Tweet metadata was read through a public status API. Attached charts were not transcribed and are not data.

| Status | Created | What the text supports |
| --- | --- | --- |
| https://x.com/WarrenPies/status/1882548438136651927 | 2025-01-23 21:58 UTC | Calls the CoreLogic single-family rent index, not home prices, a 14-year low and expects shelter disinflation. The same day's CoreLogic release is the SFRI for November 2024, with national rent growth stated at 1.5% year over year and described as the lowest annual increase in more than 14 years. |
| https://x.com/WarrenPies/status/1762296948264972502 | 2024-02-27 02:01 UTC, which is the evening of 2024-02-26 in the US East | January OER month-on-month growth exceeded CPI rent by 0.2 percentage point, the largest such gap since 1995. The text does not mention single-family versus multifamily composition. |
| https://x.com/WarrenPies/status/2001651953080906047 | 2025-12-18 13:53 UTC | Says shelter inflation had the lowest year-on-year reading since 2021 and that CoreLogic single-family rents point to more shelter disinflation. The text gives no SFRI number. |

A separate claim that a thread said the prior year's SFRI had flagged shelter stickiness was not retrieved. That claim stays unverified.

The January 2024 OER-versus-rent gap has an official BLS explanation that is easy to confuse with the tweet. Beginning with January 2023 data, BLS reweights OER unit observations toward the American Community Survey mix of single-family detached versus other owner units. BLS states that in January 2024 the single-family-detached share of OER weights rose by about five percentage points. The rent index does not receive that structure-type adjustment. Source: https://www.bls.gov/cpi/notices/2024/rent-oer-information.htm and the January 2023 methodology notice https://www.bls.gov/cpi/notices/2023/methodology-changes-2023.htm.

## Publication calendar versus a pre-CPI use

BLS schedule pages:

- August 2026 CPI: Friday, September 11, 2026, 08:30 ET. https://www.bls.gov/schedule/2026/09_sched_list.htm
- September 2026 CPI: Wednesday, October 14, 2026, 08:30 ET. https://www.bls.gov/schedule/2026/10_sched_list.htm
- October 2026 CPI: Tuesday, November 10, 2026, 08:30 ET. https://www.bls.gov/schedule/news_release/cpi.htm

That October CPI is outside the cutoff. A BLS API read on 2026-11-10, before that release was visible in the API, showed `CUSR0000SEHC01` through September 2026 at 445.195 and October 2025 as unavailable (`-`, footnote X, 2025 appropriations lapse). FRED's series page, cited as retrieved November 9, 2026, showed the same September endpoint and a next release of November 10, 2026.

The August 2026 SFRI press release is dated October 15, 2026, the day after the September CPI release and more than a month after the August CPI release. On the dates actually observed, the public SFRI write-up is not a same-month pre-CPI input, and it missed the following month's CPI as well. If a paying feed really arrives about three weeks after month-end, August data would have fallen around September 21, after the August CPI and before the September CPI. That would be a possible input to the next print only. It was not observed here and cannot be assumed.

## Why headlines are not a sample

Checked releases, used only as bibliography:

| Release date | What the page states | Why it is not a data point in this study |
| --- | --- | --- |
| 2025-01-23 | November 2024 national SFRI +1.5% year over year, lowest in more than 14 years. https://www.cotality.com/press-releases/us-annual-single-family-rent-growth-dips-below-2-in-november | One revised-later headline. The press license limits republication. |
| 2025-12-18 | October 2025 +0.9% year over year; title says growth remains at a 15-year low. https://www.cotality.com/press-releases/single-family-rent-growth-remains-at-a-15-year-low | Same limitation. Matches the date of the third Pies post, not a chart digitization. |
| 2026-09-17 | Subhead: July 2026 +1.8% year over year. https://www.cotality.com/press-releases/annual-single-family-rent-growth-returns-to-seasonal-norms | Superseded or contradicted by the next release's body. |
| 2026-10-15 | Subhead: August 2026 +2.0% year over year. Body: July 2026 +2.0% year over year, a slight decrease from the prior year's 2.1%, and the sixth month of faster growth. https://www.cotality.com/press-releases/annual-single-family-rent-growth-accelerated-for-the-sixth-consecutive-month | July cannot be both the prior release's 1.8% and this body sentence's 2.0% without either a revision or a drafting error, and the page also assigns 2.0% to August. The study does not choose. The chart was not digitized. Next release announced for November 19, 2026, covering September 2026, after the cutoff. |

## OER identity and the holes a later test must keep

Targets named in the research issue:

- `CUSR0000SEHC01`, CPI-U owners' equivalent rent of primary residence, US city average, seasonally adjusted.
- `CUSR0000SEHA`, CPI-U rent of primary residence, US city average, seasonally adjusted, as the rent comparison, not as a second SFRI.

NSA counterparts are `CUUR0000SEHC01` and `CUUR0000SEHA`. Seasonally adjusted CPI is revised when seasonal factors are updated, so a latest-vintage SA backtest is not a real-time print test. NSA index levels are the more stable public history. October 2025 is a hard hole, not a month to interpolate. Any month-on-month change that needs the October 2025 level, including November 2025, is unavailable.

OER is estimated from the CPI housing survey of continuing and new tenants, on a panel, and then reweighted to owner structure type. SFRI is a new-listing repeat-rent index for single-family and condominium MLS rents. A lead of SFRI over OER, if it exists, is a new-lease versus stock-rent lead plus a composition difference. It is not evidence, by itself, that the next one-month OER print is forecastable.

## Acquisition required before any SFRI model

A later study needs all of the following. Missing any one of them leaves the direct test blocked.

1. The licensed national Cotality SFRI composite, as index levels or as monthly and year-over-year changes, monthly from at least 2010 through the last month available on 2026-11-09.
2. Real-time vintages, or a first-print file plus the later revised file. The publisher says the index is fully revised every release. A single current vintage cannot support a publication-date-safe backtest.
3. The timestamp at which each vintage would have been in a customer's hands. The press calendar and the "three weeks after month-end" product sentence are not the same clock.
4. Written rights to store the series for private research. The press license does not grant that for the headline numbers, and this repository will not rebuild the index from them.
5. Explicit exclusion of Cotality HPI, Case-Shiller, and Zillow ZORI from that file.

## What may still be computed

Zillow's Observed Rent Index is a public, revised, smoothed asking-rent index. The research page describes it as stock-weighted and built from listed rents between the 35th and 65th percentiles, with all-homes and single-family cuts. https://www.zillow.com/research/data/ Downloading it for a labeled sensitivity is feasible. Using it as SFRI is not. Case-Shiller (`CSUSHPISA`) is the separate house-price hypothesis associated with a longer Dallas Fed lag. It is not part of the blocked SFRI verdict, and a failed FRED download is not a reason to swap in another price index.

No Market Watch context series and no one-month CPI weight should be added from SFRI on the evidence available at this cutoff.
