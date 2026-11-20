# CoreLogic SFRI and CPI owners' equivalent rent

Decision date: 2026-11-10. Information cutoff: 2026-11-09. Final review: Grok 4.7. Arithmetic check: Composer 2.5, `verification/VERIFICATION.md`, verdict PASS on the proxy figures it recomputed. This package changes no production series, score, dashboard, schedule, or workflow.

## Decision

**No-go on Cotality/CoreLogic Single-Family Rent Index (SFRI) as a Market Watch context series. No demonstrated one-month CPI edge.**

The direct test cannot be run. SFRI is a licensed repeat-rent index, not a public file, and it is not the Cotality home-price index. Press headlines are fully revised at each release and are not a history. The latest pre-cutoff release contradicts itself, so this study does not take a September 2026 shelter call from SFRI and does not use the October 2026 CPI, which was scheduled for 2026-11-10.

A separate Zillow Observed Rent Index (ZORI) exercise, labeled as not SFRI, does not show a stable one-month or three-month gain over OER's own trailing mean and an autoregression. A year-on-year lead near 12 months appears in overlapping correlations. That is the familiar new-lease versus stock-rent contour. It is not a pre-CPI print model, and it is not an SFRI result.

## What was verified about the claim

Warren Pies's posts were checked as text. Charts were not read.

- On 2025-01-23 he wrote that the CoreLogic single-family rent index, not home prices, was at a 14-year low and that shelter disinflation was ahead. The same day's CoreLogic release is the SFRI for November 2024, national growth stated at 1.5% year over year. https://x.com/WarrenPies/status/1882548438136651927 and https://www.cotality.com/press-releases/us-annual-single-family-rent-growth-dips-below-2-in-november
- On the evening of 2024-02-26 US Eastern he wrote about the January OER-versus-rent gap, the largest since 1995. The text does not mention single-family versus multifamily composition. https://x.com/WarrenPies/status/1762296948264972502
- On 2025-12-18 he wrote that CoreLogic single-family rents still pointed to more shelter disinflation, without a number in the text. The same day's Cotality release states October 2025 national growth of 0.9% year over year. https://x.com/WarrenPies/status/2001651953080906047 and https://www.cotality.com/press-releases/single-family-rent-growth-remains-at-a-15-year-low

A further claim that a thread credited the prior year's SFRI with flagging shelter stickiness was not retrieved. It stays unverified.

BLS, not the tweet, documents the January 2024 composition break: from January 2023, OER unit weights are adjusted toward the detached-owner mix, and in January 2024 that detached share rose by about five percentage points. Rent does not get that adjustment. https://www.bls.gov/cpi/notices/2024/rent-oer-information.htm

## Why the SFRI sample stops here

The product page sells a national and CBSA file through flat file, cloud, and REAS. It says the commercial update is about three weeks after month-end. https://www.cotality.com/products/single-family-rent-index

Public releases say the index is fully revised every month. Observed press dates are slower than three weeks. August 2026 CPI was released 2026-09-11. September 2026 CPI was released 2026-10-14. The August 2026 SFRI press page is dated 2026-10-15, after both. On that calendar the public write-up is not an input to the same month's CPI or to the next one.

The 2026-10-15 page cannot be used even as a single headline. Its subhead assigns +2.0% year over year to August 2026. Its body assigns +2.0% to July 2026 and calls that a slight decrease from the prior year's 2.1%, while the title says a sixth month of acceleration. The prior release, 2026-09-17, had already stated July 2026 at +1.8%. Those sentences are recorded in `data/press_release_citations.csv` and are not averaged into a series. The chart was not digitized. The next release, September 2026 data on 2026-11-19, is after the cutoff.

FRED did not return Case-Shiller from this environment. No other house-price index was substituted. The Dallas Fed house-price lag remains a different hypothesis and was not tested.

## OER sample that was feasible

Frozen file: `data/bls_cpi_shelter_through_2026-09.csv`, retrieved 2026-11-10 03:24 UTC from the BLS API.

| Column | Series | Definition |
| --- | --- | --- |
| `oer_sa` | `CUSR0000SEHC01` | CPI-U owners' equivalent rent of primary residence, US city average, seasonally adjusted |
| `oer_nsa` | `CUUR0000SEHC01` | Same item, not seasonally adjusted |
| `rent_sa` | `CUSR0000SEHA` | CPI-U rent of primary residence, seasonally adjusted |
| `rent_nsa` | `CUUR0000SEHA` | Rent of primary residence, not seasonally adjusted |

September 2026 `oer_sa` is 445.195, matching the pre-release probe. October 2025 is blank because of the appropriations lapse. November 2025 month-on-month is therefore undefined. Nothing after September 2026 is in the file. The independent check confirmed those gates.

Seasonally adjusted CPI is not a real-time print history. BLS described the originally published January 2024 changes as about 0.6% for OER and 0.4% for rent. This vintage is 0.511% and 0.352%. The OER-minus-rent gap of 0.159 percentage points is larger than every month from February 2012 through December 2023 in this file (143 months; the previous maximum was 0.094). That documents the methodology break. It also shows why a latest-vintage SA backtest overstates what an analyst knew on release morning.

## Proxy result, which is not an SFRI result

ZORI here is the United States row of Zillow's smoothed all-homes-plus-multifamily index and, separately, the smoothed single-family index. Zillow restates the whole history each release. The forecast exercise uses that one snapshot with a lag rule of "through month t−1 only." It is not a vintage-dated publication test. Details and the horse race are in `PROXY_ANALYSIS.md`. Figures below are the ones the independent script reproduced, except the year-on-year lag peak, which was recomputed directly from the frozen CSV during final review (lag 13, correlation 0.835, n = 115).

One-month OER SA percent change, rolling origin, common sample of 76 months from 2020 through September 2026:

| Model | MAE, percentage points |
| --- | ---: |
| Last month's change | 0.074 |
| Trailing three-month mean | 0.064 |
| AR(3) | 0.063 |
| AR(3) plus latest ZORI year-on-year | 0.061 |
| AR(3) plus ZORI year-on-year lagged 12 months | 0.066 |

The 0.002 point SA improvement versus the AR is smaller than the 0.1 point resolution at which the print is discussed. It is not stable. In 2020–2022 the ZORI term is worse than the AR (0.065 versus 0.061, n = 36). The SA dip appears in 2023–2026 (0.058 versus 0.064, n = 40). On not-seasonally-adjusted OER the same ZORI term is worse than both the trailing mean (0.068 versus 0.066) and the AR (0.067). The pre-specified 12-month lead, which is the horizon the overlapping correlations pick, raises one-month error. A pre-2020 window exists only if that 12-month term is dropped, and then only 11 months qualify; ZORI ties the trailing mean and does not beat it.

Three-month cumulative SA change, non-overlapping origins, common sample n = 24: trailing-mean MAE 0.170, direct AR 0.189, direct AR plus ZORI 0.247. Adding ZORI makes the three-month path worse. Scoring models on different month sets had understated the trailing-mean error; the common-sample comparison is the one that counts.

Twelve-month direction, non-overlapping, n = 10: the sign of (ZORI year-on-year minus OER year-on-year) matches the subsequent change in OER year-on-year in 7 of 10 origins. Always predicting a decline, and a three-month momentum rule, each go 5 of 10. Ten origins cannot carry a model. The six-month rate from the same function (16 of 20 for the gap rule) was not separately recomputed. Overlapping year-on-year hit rates are descriptive only.

September 2026 year-on-year, proxy snapshot only: OER SA 3.26%, rent SA 2.78%, ZORI all-homes 2.70%, ZORI single-family 3.13%. The all-homes gap versus OER is −0.56 percentage points. The single-family ZORI gap is about −0.14 points. The sign of "market rent is cooler than OER" depends on the ZORI cut. Neither number is SFRI, and neither is an October 2026 CPI forecast.

## What would reopen the question

A later study needs a licensed national SFRI composite from at least 2010 through the last month available on the cutoff, as levels or as monthly and yearly changes; real-time vintages or a first print paired with the later revised file, because the publisher revises the whole index every release; the timestamp when that vintage was actually in hand; and rights to store it for private research. The file must not be Cotality HPI, Case-Shiller, or ZORI. Until that file exists, Market Watch should not display an SFRI context series and should not put an SFRI term in a one-month CPI model.
