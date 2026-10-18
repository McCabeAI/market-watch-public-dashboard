# Canadian CPI: September 2026 nowcast and proposed release engine

Research completed October 17, 2026. Quantitative inputs frozen to information available by October 16; target release October 19 at 08:30 ET. Public calendar consensus was checked again on October 17 and is identified separately. Research only: no production code, repository data, Market Watch, ACP, schedules or listeners were changed.

## Decision and release call

**A Canadian CPI nowcaster can materially outperform simple historical models. This research does not establish that it can outperform economist consensus.** The clearest advantage comes from Canadian retail fuel prices, not importing the U.S. inflation release. A limited Canadian model is justified; a large Canada–U.S. regression is not.

The recommended September call is **+0.13% headline NSA month-on-month, approximately +0.50% SA, and 3.1% year-on-year**. The most likely rounded NSA print is +0.1%; +0.2% is close enough that the distinction should not carry much conviction. The Canadian gasoline estimate is +5.53% NSA, contributing +0.213 percentage points. Seasonal travel declines offset much of this increase.

The Canadian direct-input model reduces headline monthly MAE from 0.266 to 0.204 percentage points over January 2017–August 2026. Over January 2019–August 2026, when the Canadian fuel bridges have enough training observations, MAE is 0.190 versus 0.266 for the historical model and 0.262 for a seasonal-average benchmark. Adding selected cross-border predictors lowers MAE only to 0.186. That incremental improvement is small; its economic value and robustness to vintage limitations remain unproven.

| September target | Central estimate | Reasonable range | Interpretation |
|---|---:|---:|---|
| Headline NSA MoM | +0.133%; rounded +0.1% | −0.1% to +0.4% | Approximate central 80% historical-error interval |
| Headline SA MoM | +0.498%; rounded +0.5% | +0.3% to +0.8% | Canadian seasonal bridge; less certain than NSA |
| Headline YoY | 3.108%; rounded 3.1% | 2.9% to 3.4% | Uses September 2025 index, not August YoY plus MoM |
| Excluding food and energy, NSA MoM | +0.038%; rounded 0.0% | −0.2% to +0.3% | Separate Canadian historical aggregate forecast; scenario range |
| Excluding food and energy, SA MoM | About +0.24%; rounded +0.2% | 0.0% to +0.4% | Own Canadian seasonal bridge; scenario range |
| Excluding food and energy, YoY | 2.23%; rounded 2.2% | 2.0% to 2.5% | Independent aggregate model, not a reconstructed headline residual |
| CPI-trim YoY, forecast of official release | 1.845%; roughly 1.8–1.9% | 1.7% to 2.0% | Near a rounding boundary; do not trade 1.8 versus 1.9 as a high-confidence distinction |
| CPI-median YoY, forecast of official release | 1.904%; rounded 1.9% | 1.7% to 2.1% | Includes first-release revision risk |
| CPI-trim / median monthly rates | +0.182% / +0.179% | Approximately ±0.15 pp | Forecasts from official index histories, not official component reconstructions |
| Trim / median 3-month annualized | 2.58% / 2.53% | Revision-sensitive | More useful for underlying momentum than gasoline-driven headline YoY |
| Excluding gasoline YoY | About 2.3% | 2.0% to 2.6% | Independent historical aggregate cross-check |
| CPI-common | No defensible release estimate | — | August 2.6% is context, not a September forecast |

The headline and core intervals are empirical guides, not calibrated probabilities guaranteed in the current shock. The headline 90% error-based interval is substantially wider, approximately −0.25% to +0.55% NSA. Core ranges come from only 38 genuinely release-vintage forecasts. Special-aggregate ranges are judgemental, explicitly not backtested coverage claims.

The exact headline arithmetic is:

`September index = 169.8 × (1 + 0.1325244 / 100) = 170.0250`

`September YoY = 100 × (170.0250 / 164.9 − 1) = 3.1080%`

The median of the previous five September differences between Canadian SA and NSA monthly inflation is +0.3654 pp. Adding it to +0.1325 gives +0.4979% SA. This does not use U.S. seasonal factors. A separate SA headline model using U.S. CPI gives +0.443%, a useful cross-check, not an additional shock to add to the component forecast.

## September contribution accounting

Contributions below sum to +0.1325 pp. They are monthly contributions to NSA headline inflation, not YoY contributions. More decimals are shown for auditability, not forecast precision.

| Mutually exclusive block | Contribution, percentage points | Evidence status |
|---|---:|---|
| Gasoline | +0.2133 | Observed Canadian pump-price proxy; modeled CPI bridge |
| Transportation excluding gasoline | −0.1710 | Modeled, predominantly seasonal travel behavior |
| Fuel oil and other fuels | +0.0279 | Observed Canadian furnace-oil proxy; modeled CPI bridge |
| Shelter excluding fuel oil | +0.0507 | Canadian historical models plus lagged house-only NHPI bridge |
| Food | −0.0431 | Canadian seasonal/momentum model |
| Household operations, furnishings and equipment | +0.0005 | Modeled |
| Clothing and footwear | +0.0725 | Canadian autumn seasonality, not U.S. apparel replacement |
| Health and personal care | +0.0021 | Modeled |
| Recreation, education and reading | −0.0186 | Modeled; includes seasonal accommodation/tour effects |
| Alcohol, tobacco and recreational cannabis | −0.0019 | Modeled |
| **Total** | **+0.1325** | **Research nowcast** |

The model starts with forecasts for eight official major groups, then replaces the baseline changes of selected children by validated direct bridges. This is a transparent additive forecasting bridge. It is not an exact replication of Statistics Canada's lower-level aggregation, and the modeled parent forecast need not equal independently forecast child totals. Production should reconcile a complete mutually exclusive leaf partition.

NRCan's national monthly gasoline average rose from **177.8¢/L in August to 187.5¢/L in September**, or 5.4556%. The fitted CPI bridge gives 5.5286%. The April-link gasoline weight is 4.01%; its price-updated August importance is 3.8589%, giving `0.0385886 × 5.5286 = 0.21334 pp`. NRCan's price level is not the StatCan gasoline sample: StatCan's August average retail gasoline series is 173.8¢/L. A bridge is necessary even with a close historical relationship.

For comparison, the U.S. gasoline print is +9.1% SA but the downloaded U.S. NSA indexes, 359.738 and 383.182, imply +6.52% NSA. Comparing Canadian +5.53% NSA directly with U.S. +9.1% SA would mix seasonal bases. [S11]

NRCan furnace oil rose from 214.1¢/L to 239.2¢/L, or 11.72%; the CPI bridge estimates +11.66%. Diesel rose from 231.0¢/L to 260.7¢/L, or 12.86%, but is not added as a separate household gasoline component. Its freight effects require lagged pass-through evidence.

The historical Canadian airfare model implies approximately −11.77% NSA in September; accommodation approximately −3.42%. These are forecasts, not observed fares. Airfare's price-updated weight is about 1.33%, so a five-percentage-point miss changes headline by roughly 0.067 pp. This is a larger remaining risk than the incremental U.S. goods signal.

**Upside risks:** (1) airfares/accommodation fall much less than their Canadian seasonal pattern; (2) StatCan's gasoline sample rises more than NRCan's national average, or fuel costs pass through rapidly beyond energy; (3) food promotions and normal September declines fail to materialize, including tariff-related goods increases.

**Downside risks:** (1) stronger post-summer travel discounting; (2) StatCan's fuel collection/geography yields a smaller increase than the public proxy; (3) stronger grocery, vehicle or communications discounts than the historical models imply. These are separate component risks, not additive confidence bounds.

The September announcement extending federal fuel-excise relief continues an existing measure; it is not a new full September tax cut. Likewise, a tariff rate cannot be added mechanically to CPI. Inventory timing, import origin, exemptions, retailer margins and tax treatment matter. The official September counter-tariff changes belong in dated exposure scenarios until pass-through is demonstrated. [S12–S13]

## What would be a surprise on Monday?

The latest public Trading Economics calendar, retrieved October 17, shows **+0.2% NSA consensus, 1.9% trim and 2.0% median**. Its headline YoY consensus cell is blank; **3.2% is its own forecast, not a survey median**. +0.2% NSA mechanically implies about 3.18% YoY using the published index base, but that does not establish an independently surveyed YoY consensus. These calendar observations were not used to fit or set the forecast. Their October 16 intraday vintage was not captured. Another calendar returned conflicting trim values, which were rejected rather than averaged. [S18]

| Release outcome | Relative to this nowcast and the public calendar | Reading |
|---|---|---|
| NSA at least +0.4%, roughly 3.4% YoY; trim at least 2.1% and median at least 2.2% | Clearly above both model and cited core/monthly consensus | Broadly hawkish, especially if prior core months revise up |
| NSA +0.1% to +0.2%, trim 1.8–1.9%, median 1.9–2.0% | Near both estimates | Energy-led headline pressure; little evidence of a new underlying acceleration |
| NSA 0.0% or below, roughly 3.0% YoY or lower; trim at most 1.7%, median at most 1.8% | Below both model and cited core/monthly consensus | Broadly dovish if confirmed by monthly core and revisions |
| High headline but soft trim/median | Mixed | Fuel surprise, not automatically a policy surprise |

These are trading interpretation thresholds, not estimated market-response functions. A merely rounded 0.1-point miss is small relative to model error. Read the revised monthly core path and 3-month annualized rates before labeling the release.

## Canadian architecture and what is observable

The 2025 expenditure basket applies from May 2026, with April 2026 as its link month. The eight link-month shares are food 16.93%, shelter 28.30%, household operations/furnishings/equipment 12.80%, clothing/footwear 4.50%, transportation 18.54%, health/personal care 5.40%, recreation/education/reading 9.81%, and alcohol/tobacco/cannabis 3.73%. The 0.01-point excess is published rounding. Rent is 7.45%, mortgage interest 5.21%, replacement cost 4.38%, gasoline 4.01%, and passenger-vehicle insurance 2.49%. These are Canadian expenditure weights. [S1–S3]

Statistics Canada uses elementary price indexes, quality adjustments and fixed-quantity Lowe aggregation within a basket, with chain links across baskets. For within-basket monthly contributions, the relevant share is the link weight price-updated through the preceding month:

`s_i,t−1 = w_i,link × (I_i,t−1 / I_i,link) / (I_all,t−1 / I_all,link)`

`forecast headline MoM = Σ s_i,t−1 × forecast component MoM`

Rounded public weights/indexes create small residuals. Do not compute YoY contributions by simply multiplying current weights by component YoY rates across basket changes. The eight-group classification and full published parent/member structure are available in the table metadata; the evidence package includes the basket metadata and a vector registry. [S2–S4]

Historical link dates used in the corrected aggregation are December 2016 for the 2015 basket, December 2018 for 2017, May 2021 for 2020, and April 2022/2023/2024/2025/2026 for the subsequent annual baskets. Earlier dates are documented in the research script. The 2020 expenditure shift, May 2022 introduction of separate new/used vehicle indexes, and later category/collection changes prevent assuming constant relationships across the full sample. [S3]

| Component | Canadian collection/methodology | Forecast implication |
|---|---|---|
| Gasoline | High-frequency administrative price collection over the month | Canadian pump prices dominate crude and U.S. CPI as the late-month observable |
| Electricity/natural gas | Utility rates, tariff structures and administrative/provider information | Reconstruct province/customer bills, including fees, taxes and rebates; spot gas is not the household bill |
| Food at home | Scanner transactions plus other price collection; quantity/quality adjustments | Public average prices are delayed unit-value products, not a live CPI substitute; September scanner microdata were not accessible |
| Restaurants | Sampled menu/service prices and tax treatment | Canadian wages/input costs are lagged hypotheses; U.S. restaurant CPI failed the useful-increment test |
| Rent | LFS rent information with quality adjustment; includes incumbent tenancies | Asking rents measure a different flow; never substitute U.S. rent or OER |
| Mortgage interest | Mortgage stock/rate and house-price model, including renewal dynamics | Outstanding effective rates and historical purchase prices matter; today's five-year offer rate is insufficient |
| Replacement cost | Depreciation/replacement concept tied to house-only new-home prices | Lagged Canadian NHPI is useful; land and resale appreciation are not direct replacements |
| Property tax | Annual update concentrated in October | September central change is zero; do not smear October's update into September |
| Home/vehicle insurance | Since April 2025, broker-quote data with 12-month time-dummy hedonic models | Approved rate filings or an individual's renewal are incomplete proxies; quotes are not existing-policy payments |
| New/used vehicles | Canadian transaction/quality adjustment; separate published series from April 2022 base | Wholesale/listing prices need a retail bridge; no fictitious long used-vehicle history |
| Air transportation | API-based fare collection; route/product and purchase/travel timing matter | Same-month U.S. airfare is not a valid replacement; booking-horizon archive needed |
| Travel tours/accommodation/car rental | Online price collection with distinctive seasonal profiles | Observing today's quote for a future trip is not observing September's CPI sample |
| Apparel/household goods/electronics | Web, sampled prices and category-specific quality adjustment | Common sale seasons can produce misleading raw correlation |
| Communications | Cellular index combines provider transaction information and web prices | Posted plans alone miss transaction mix and quality changes |
| Health/personal care | Canadian consumer-paid goods/services; sampling and quality adjustment | U.S. health insurance and hospital/PCE payment concepts do not transfer |

Most traditional monthly collection occurs in the first two weeks, but timing varies; gasoline covers the month, and scanner/API/administrative feeds have their own windows. Imputation uses relevant donor price movements where observations are unavailable, and pandemic closures created special treatments. A production registry needs the specific collection window, not a universal month-end assumption. [S5–S10]

## Tests performed and what they establish

The evidence package contains individual forecasts, actuals, correlations, transformations and scripts. Prices are converted to monthly percentage changes; level correlations were not used. The main component model uses a rolling 120-month window, calendar-month indicators, previous monthly inflation and a prior three-month mean. Nonseasonal coefficients receive a small fixed ridge penalty of 1 after training-window scaling. Usually at least 60 observations are required; short/direct histories use at least 24. There is no full-sample optimization of the penalty.

Models examined:

* **A:** Canadian component history only, aggregated from eight major groups.
* **B:** A with a Canadian pump-price gasoline bridge.
* **B2:** B plus Canadian furnace-oil and lagged NHPI replacement-cost bridges. This is the recommended operational candidate.
* **C/C2:** corresponding direct model plus economically mapped cross-border/FX/oil candidates selected using only prior errors.
* **D/D2:** half of the C/C2 revision to B/B2; the direct gasoline forecast is retained.

For the online selection, a candidate must beat A's MAE by at least 5% over the previous 36 months, with at least 24 usable realized errors. Selection is component-specific. Candidates include same-month U.S., U.S. plus FX/WTI, lagged U.S., Canadian FX/WTI, and mapped PPI. The next observation is never used to choose its model. Component deltas are applied only to disjoint children; no parent/child double-counting. These are exploratory research specifications, not a pre-registered untouched final holdout.

Actual historical release dates gate U.S. inputs. Same-day U.S./Canadian releases are conservatively treated as unavailable. Of 116 evaluation months, same-month CPI is eligible in 112 and PPI in 108. Four CPI-ineligible months are June, September, October and November 2025. Missing current releases fall back to the Canadian baseline; they are not silently backfilled.

The important limitation: the broad component/SA/PPI exercise is **latest-history pseudo-out-of-sample**, not a fully vintage-clean backtest. Published NSA CPI is generally unrevised, but seasonal factors, PPI, NHPI and some source histories can revise. NRCan historical pages were downloaded now, without a complete archive of historical publication timestamps. The Canadian fuel availability assumption is that the completed previous month's daily/monthly price observations were available before the CPI release. Mortgage data use a conservative two-month lag, rather than a fully reconstructed historical release calendar. These limitations cannot be cured by calling a regression “real time.”

### Headline results

All errors below are percentage points of monthly NSA inflation. Bias is forecast minus actual; direction includes exact zero as its own sign.

| Model, Jan 2017–Aug 2026, n=116 | MAE | RMSE | Bias | Direction |
|---|---:|---:|---:|---:|
| Previous-month component carry | 0.414 | 0.507 | +0.006 | 56.9% |
| Prior 3-month component mean | 0.347 | 0.443 | +0.003 | 62.1% |
| Same-month previous-five-year component average | 0.260 | 0.348 | −0.035 | 80.2% |
| A: Canadian seasonal/momentum | 0.266 | 0.339 | −0.050 | 76.7% |
| B2: Canadian direct bridges | 0.204 | 0.262 | −0.046 | 82.8% |
| C2: online-selected cross-border additions | 0.202 | 0.260 | −0.044 | 82.8% |
| D2: half-weight ensemble additions | 0.203 | 0.261 | −0.045 | 82.8% |

A direct headline AR(1), separately tested rather than aggregated, has MAE 0.319 and RMSE 0.398. Direct headline seasonal-average MAE is 0.264. The improvement is not just against a deliberately weak carry benchmark.

| Evaluation window | n | A MAE | B2 MAE | C2 MAE | D2 MAE | Seasonal-average MAE |
|---|---:|---:|---:|---:|---:|---:|
| 2019–Aug 2026 | 92 | 0.266 | 0.190 | 0.186 | 0.188 | 0.262 |
| 2021–23 | 36 | 0.296 | 0.196 | 0.189 | 0.192 | 0.310 |
| 2025–Aug 2026 | 20 | 0.260 | 0.170 | 0.169 | 0.170 | 0.214 |
| Actual gasoline move at least 5% in absolute value | 38 | 0.366 | 0.227 | 0.224 | 0.226 | 0.395 |

The energy-shock classification is a retrospective evaluation slice, not advance knowledge supplied to the forecast. The 2025–26 slice includes tariff disturbances but does not identify a causal tariff coefficient. Twenty observations are insufficient to estimate a reliable separate tariff regime. The models still underpredicted 2021–23: B2 bias is −0.147 pp. A causal trailing-36-month bias correction worsened MAE, so it was rejected.

A six-month circular block bootstrap, 10,000 draws, gives B2's MAE improvement over A as 0.0615 pp, with a 95% interval of [0.0378, 0.0868]. Against seasonal average, improvement is 0.0553 [0.0257, 0.0913]. C2's incremental gain over B2 is only 0.00260 [0.00015, 0.00522]. The nominal bootstrap interval is just above zero, but the magnitude is economically small. These intervals describe this sample; they do not account for every exploratory design choice, multiple comparison or data-vintage issue.

C2 is the numerical winner, but **B2 is the recommended model because the extra complexity has not earned a robust incremental aggregate edge**. B2, C2 and D2 September forecasts are +0.1325%, +0.1271% and +0.1298%, respectively. The model-choice uncertainty is much smaller than the residual forecasting uncertainty.

### Direct Canadian inputs

| Component, 2019–Aug 2026 | Historical MAE | Direct-input MAE | Direct RMSE | 2025–26 direct MAE |
|---|---:|---:|---:|---:|
| Gasoline: NRCan pump bridge | 4.510 | 0.568 | 0.764 | 0.389 |
| Fuel oil: NRCan furnace-oil bridge | 4.640 | 1.955 | 2.850 | 1.143 |
| Replacement cost: previous-month house-only NHPI | 0.246 | 0.084 | 0.125 | 0.072 |
| Mortgage interest: two-month-lag effective outstanding rate | 0.185 | 0.156 | 0.211 | 0.101 |

Mortgage's recent historical baseline MAE is only 0.084, better than the 0.101 rate bridge. It is not included in B2. Its September estimates are +0.404% historical versus +0.317% rate-augmented. Build the stock/renewal model only after a stronger vintage-aware test.

Gasoline plus U.S. CPI lowers full-window gasoline MAE slightly, from 0.568 to 0.538, but increases RMSE from 0.764 to 0.788. In 2025–26 it worsens MAE from 0.389 to 0.447. The September estimate changes only from 5.529% to 5.674%. Keep U.S. gasoline as a fallback/cross-check, not an additional full-weight input after Canadian pumps.

### Canada–U.S. evidence

The table uses monthly NSA changes. “Adjusted r” removes calendar-month means for a descriptive seasonality check; it is not official SA and is not used as a future-aware forecasting input. Beta is the contemporaneous U.S. coefficient controlling for calendar months, USD/CAD and WTI. Main correlations use 1997–August 2026 where available; vehicle and electronics histories are shorter. MAE uses the release-gated evaluation sample, generally 116 months, with only 28 new/used-vehicle forecasts. Full sample sizes and rolling correlations are in the CSVs.

| Canadian component | Raw r | Adjusted r | Lag-1 r | Controlled beta | A MAE | U.S.-only MAE | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| Gasoline | .882 | .868 | .189 | .648 | 4.408 | 2.111 | Useful fallback; Canadian pumps better |
| Energy | .830 | .826 | .214 | .698 | 2.701 | 1.397 | Mostly common fuel shock; do not double count |
| Meat | .404 | .397 | .304 | .388 | .767 | .687 | Best nonenergy candidate |
| Grocery food | .265 | .421 | .173 | .582 | .419 | .407 | Small gain; broad mapping |
| Bakery/cereals | .260 | .303 | .193 | .478 | .610 | .589 | Small gain, below preferred inclusion threshold |
| Fresh fruit | .275 | .350 | .136 | .604 | 2.017 | 1.944 | Modest, not robust enough for central use |
| Fresh vegetables | .556 | .664 | .202 | 1.219 | 2.033 | 1.991 | Attractive correlation, little incremental accuracy |
| Restaurants | .160 | .163 | .137 | .563 | .370 | .381 | Reject |
| New vehicles | .126 | .184 | .086 | .511 | .630 | .636 | Reject; short Canadian history |
| Used vehicles | .233 | −.013 | .312 | −.003 | .807 | .819 | Reject contemporaneous mapping |
| Clothing | .625 | −.055 | .150 | −.086 | 1.152 | 1.160 | Raw correlation is largely seasonality |
| Furniture | .007 | −.014 | .020 | −.025 | 1.018 | 1.006 | No material gain |
| Household equipment | .282 | .214 | .189 | .212 | .684 | .659 | Small/unstable gain |
| Computers/software | .069 | .057 | .072 | .041 | .831 | .844 | Reject |
| Video equipment | .345 | .308 | .202 | .272 | .985 | .972 | Small gain; not enough for inclusion |
| Air transportation | −.205 | −.185 | .192 | −.325 | 5.868 | 5.830 | Reject mechanical mapping |
| Accommodation | .430 | .099 | .402 | .185 | 3.278 | 3.244 | Mostly common seasonality; lagged MAE 3.145 still modest |
| Health goods | .022 | .013 | .060 | .012 | .336 | .341 | Reject |
| Health services | −.121 | −.038 | −.022 | −.040 | .147 | .159 | Reject |
| Personal-care supplies | .086 | .048 | .011 | .096 | .747 | .732 | Small, insufficient gain |
| Rent | .305 | .302 | .323 | .562 | .295 | .296 | Reject; Canadian stock-rent model stays separate |

Meat is the strongest nonenergy lead: U.S.+FX/oil MAE 0.685 versus Canada-only FX/oil 0.772 and A 0.767. Its U.S. model RMSE is 0.903 versus 1.004 for A; bias improves from −0.071 to −0.035; directional accuracy rises from 66.4% to 70.7%. The improvement persists in 2021–23 and 2025–26, although its headline weight makes the aggregate gain small. It should enter a cheap shadow model, not justify a large data purchase.

Regimes matter. Gasoline correlation falls from .904 before 2020 to .845 afterward but remains strong. Clothing falls from .675 to .374 and loses virtually all correlation after seasonal removal. Fresh-vegetable correlation falls from .572 to .311. Household-equipment correlation rises from .097 to .448, so a single full-history beta is suspect. Airfare correlation changes from −.016 to −.321. These are descriptive splits, not evidence that independently fitted regime coefficients improve forecasts. Rolling 60-month correlations, lags 0–3, post-May-2022 splits and the 2025–26 slice are included in the evidence files.

Official-SA checks were also run where compatible Canadian aggregates exist. Headline SA MAE falls from 0.231 to 0.166 with U.S. headline, food from 0.307 to 0.277, and ex-food/energy from 0.148 to 0.139. Clothing worsens from 0.606 to 0.626. The ex-food/energy September forecasts are +0.207% and +0.216%. These modest core results support a cross-check; current revised SA histories prevent treating them as proven first-release gains. Component-level official Canadian SA series are not publicly available for every tested pair.

Seven broad U.S. PPI commodity series were examined, including gasoline WPU0571, jet fuel WPU057203, motor vehicles WPU1411, textile/apparel WPU03 and household furnishings WPU12. Broad food WPU02 was also used in exploratory mappings, some too coarse to merit deployment. **No tested PPI addition establishes a robust incremental headline advantage over Canadian direct prices.** This is not a claim that every detailed industry PPI has been exhausted. U.S. September PPI's large energy shock is real; it is not a Canadian retail-price coefficient. [S11]

## Trim, median and underlying inflation

Official trim and median use a 55-component tax-adjusted, seasonally adjusted monthly distribution, fixed link-month weights, and compounding of twelve monthly results. Trim removes exactly 20% of weight from each tail, including fractional boundary weights. Median takes the first component crossing 50%. CPI-common instead uses a standardized year-on-year panel and a factor model, with substantial revision sensitivity. The Bank stopped treating common as a preferred measure in 2022, despite some legacy StatCan page labels. [S14–S16]

The public legacy 55 labels can be matched to published NSA series, but their 2025 published weights sum to **99.19%, not 100%**. This research has not resolved every classification difference. In addition, the exact component tax-adjusted/SA input panel and full-precision weights were not obtained. Therefore exact replication is **not demonstrated**.

The diagnostic proxy uses the matched legacy components, normalizes their covered weights, removes a trailing-120-month calendar effect estimated only from prior observations, and applies the official trimming/median arithmetic. It remains tax-inclusive and is called a **research proxy**, not official trim or median. Its reconstruction errors, using actual component outcomes, are:

| Proxy versus published current history, 2017–Aug 2026 | Monthly MAE | Monthly RMSE | YoY MAE | YoY RMSE |
|---|---:|---:|---:|---:|
| Research trimmed proxy | 0.067 | 0.084 | 0.186 | 0.230 |
| Research weighted-median proxy | 0.072 | 0.098 | 0.237 | 0.291 |

These are **reconstruction errors after observing components**, not forecast accuracy. They understate the total error of forecasting the components first. In 2025–26, proxy YoY MAE is 0.093 for trim and 0.190 for median. That may help diagnose breadth, but it does not support trading a one-tenth official-core surprise with confidence. The proxy September monthly rates are about +0.23% for both, somewhat higher than the official-history forecasts; this is an upside diagnostic only.

For the actual release forecast, the research uses an equal blend of the prior three- and six-month mean official index changes, compounds from August, and rolls out September 2025. This simple blend avoids choosing between nearly tied specifications after inspecting a short sample.

| Forecast official YoY, true release-vintage test Feb 2023–Mar 2026, n=38 | Trim MAE | Median MAE |
|---|---:|---:|
| Carry prior published YoY | 0.161 | 0.182 |
| Carry prior monthly rate, roll base | 0.100 | 0.141 |
| Prior 3-month mean rate, roll base | 0.102 | 0.123 |
| Prior 6-month mean rate, roll base | 0.095 | 0.114 |
| Equal 3/6-month blend | 0.097 | 0.116 |

The vintage test trains from each previous release's history and scores the next first-published YoY value. The downloaded vintage table ends at the April 2026 release; it does not supply May–September release vintages. This is an explicit coverage limit. The 2026 revision-policy change also limits comparability with earlier years. Index levels are rounded, so calculations near a reporting threshold are approximate.

CPI-common is not forecast here: an unadjusted PCA would not reproduce its tax-adjusted input panel, scaling or revisions. Better release interpretation includes trim/median 3-month annualized rates, ex-food/energy SA, ex-gasoline YoY, a tax-adjusted aggregate, and an explicitly labeled measure excluding mortgage interest. The latter and inflation-breadth indicators should be added only with a reconciled component partition; no untested numerical forecast is supplied for them.

## Data acquisition priorities and pre-release availability

Tier 1 means demonstrated component value or indispensable infrastructure. Tier 2 means a plausible incremental source that still needs validation. Tier 3 means no proven value sufficient to justify operational complexity. “Known” refers to September information by October 16, not whether the source's name is public. All monetary subscription costs not verified are marked unknown; no paid feed was purchased.

| Tier | Dataset/source and identifier | Frequency / usual lag | September known? Historical as-of treatment | Depth / cost / difficulty | Expected value |
|---|---|---|---|---|---|
| 1 | StatCan CPI 18-10-0004-01 | Monthly, following-month release | No; targets only through August | Long history; free; low | Required targets, histories, special aggregates |
| 1 | StatCan SA CPI 18-10-0006-01 | Monthly; revisions | No; latest-vintage backtest disclosed | 1992 onward in extract; free; low | Canadian seasonal bridge and core cross-check |
| 1 | StatCan weights 18-10-0007-01 + metadata | Annual basket, dated effective month | 2025 weights known | 1986 onward; free; low | Correct aggregation, hierarchy, regime dates |
| 1 | StatCan core 18-10-0256-01 and vintages 18-10-0259-01 | Monthly | September unknown; historical first releases used where present | Core since 1989; retrieved vintage releases Dec 2016–Apr 2026; free; moderate | Official core forecasts/revision evaluation |
| 1 | NRCan gasoline, productID=1, locationID=66; city detail | Daily/weekly/monthly; short operational lag | Yes; completed-month price observations; historical timestamps assumed, not fully archived | July 2016 onward collected here; free public pages; moderate | Largest demonstrated gain |
| 1 | NRCan furnace oil, productID=7 | Weekly/monthly available | Yes; same archive caveat | July 2016 onward collected; free; low incremental | Strong fuel-oil component gain, small basket share |
| 1 | NHPI 18-10-0205-01, house-only v111955443 | Monthly | September unavailable; August used with one-month lag | Long monthly history; free; low | Replacement-cost MAE reduced substantially |
| 1 | Actual StatCan/BLS release calendars and archived first prints | Per release | September U.S. CPI Oct 14/PPI Oct 15 known | Reconstructed evaluation calendar; free; moderate | Prevents release-order look-ahead |
| 2 | BoC/StatCan mortgage balances and rates, 10-10-0006-01 | Monthly, reporting lag | September unknown; extract through July; conservative two-month lag tested | Since 2016; free; moderate | Stock/renewal modeling; recent incremental result weak |
| 2 | BoC Valet FXUSDCAD; longer Board/FRED DEXCAUS | Daily | September known; monthly average of dated daily observations | BoC current series since 2017, longer predecessor; free; low | FX control, not an independent universal inflation signal |
| 2 | BLS meat CPI CUUR0000SAF11211; SA counterpart CUSR | Monthly, actual release gate | September known; same-month eligibility checked historically | 1997 onward used; free; low existing infrastructure | Best nonenergy U.S. candidate; shadow validation |
| 2 | NRCan diesel productID=5; refining/marketing components | Weekly/monthly | September known | Public historical pages; free; moderate | Freight and supply-shock scenarios; no direct household additive contribution |
| 2 | Provincial utility tariffs: OEB, Régie, BCUC and providers | Dated tariff changes | Effective September tariffs potentially knowable; complete bill panel not acquired | Varies; free notices; high integration | Deterministic bill mapping, value not measured here |
| 2 | Canadian retail scanner/transaction feed under license | Daily/weekly, contract-dependent | StatCan microdata not accessible; commercial September availability unverified | Vendor-dependent; cost unknown; high | Potential food improvement, must prove it before purchase |
| 2 | Canadian Black Book wholesale/retail histories | Weekly public reports, licensed detailed values | September reports exist; historical vintages need archiving | Public multi-year archive; full license cost unknown; moderate | More relevant than U.S. auction data, but not validated |
| 2 | Matched Canadian dealer/OEM transaction and incentive prices | Daily/monthly | September archive not obtained | Provider-dependent; cost unknown; high | Vehicle quality-adjusted retail bridge |
| 2 | Canadian fare/booking-horizon archive, airline/API or licensed provider | Daily at fixed booking horizons | No usable September historical panel obtained | Provider-dependent; cost unknown; high | Potentially valuable given airfare residual risk |
| 2 | Canadian hotel/tour matched-price archive | Daily/weekly | No usable September panel obtained | Provider-dependent; cost unknown; high | Seasonal travel risk; start prospective validation |
| 2 | CREA benchmark/new-resale house-price inputs; CMHC mortgage/rent data | Monthly or annual by product | Some September housing information public; not an official MIC observation | Product-dependent; free summaries/licensed detail; moderate | Lagged house-price and mortgage-cohort model |
| 2 | Rentals.ca/Urbanation asking rents | Monthly, early next month | September report available; not used as CPI rent | Public archive; free summary; moderate | Longer-lag rent pipeline, not incumbent-rent replacement |
| 2 | Canadian insurance broker quote panel | Monthly, proprietary | StatCan source panel not obtained | Vendor-dependent; cost unknown; high | Match post-April-2025 hedonic methodology; pilot only |
| 2 | Dated taxes, rebates and tariff exposure by category | Event-driven | Effective policies known where verified | Official gazettes/notices; free; moderate | Avoid mechanical tax mistakes; scenario mapping |
| 3 | StatCan retail average food prices 18-10-0245-01/02 | Monthly, well after reference month | September not known; August published Oct 7 | Current product since 2017 with changes; free; low | Useful diagnostics; no same-month release edge |
| 3 | BLS gasoline CUUR0000SETB01 and energy SA0E | Monthly | September known; exact release gate | Long history; free; low | Keep as fallback; redundant after Canadian pumps |
| 3 | Other tested BLS CPI pairs: apparel, autos, airfare, household, health, recreation | Monthly | September known; exact release gate | Variable; free; low | Most fail useful incremental OOS test; IDs in mapping CSV |
| 3 | BLS PPI WPU0571, WPU057203, WPU1411, WPU03, WPU12, WPU01/02 | Monthly, revisable | September known; exact release gate but current revisions used | Long history; free; low | No proven aggregate increment after Canadian direct prices |
| 3 | WTI/Brent: EIA via FRED DCOILWTICO/DCOILBRENTEU | Daily, short reporting lag | September known; month averages only | Decades; free; low | Useful fallback/control; pump prices capture retail shock better |
| 3 | Jet fuel and crack spreads: EIA spot series/derived spreads | Daily/weekly | September potentially known; not a retail airfare observation | Decades depending series; free public spot data; moderate | Lagged cost pressure; no demonstrated airfare edge |
| 3 | Manheim U.S. used-vehicle value index | Monthly, fifth business day; midmonth update | September report available | Long published history, methodology revisions; free summary; moderate | Canadian retail/FX/quality mismatch; not tested here |
| 3 | U.S. import/export prices; Canadian IPPI/RMPI/import-price indexes | Monthly with differing lags | U.S. releases may precede Canada CPI; September Canadian NHPI/IPPI/RMPI scheduled Oct 22 | Long histories, revisions; free; moderate | No validated September increment; never use Oct 22 outcomes |
| 3 | AAFC/Statistics Canada agricultural and wholesale prices; global food commodities | Weekly/monthly, variable lags | Mixed; source-by-source timestamp required | Varies; many free; moderate | Production costs are not retail food inflation; untested |
| 3 | Generic Canadian online grocery/apparel/electronics price scrape | Daily if collected | No consistent September matched-item archive obtained | Prospective unless licensed; engineering cost; high | Assortment, promotions and quality bias; require measured improvement |

NRCan endpoint example: `https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm?productID=1&locationID=66&frequency=M&priceYear=2026`. The downloaded HTML is retained because accessibility of the old and new sites varied. No unsupported API or commercial-access entitlement is assumed. [S17, S19–S21]

The four foundational StatCan tables, their metadata and release calendars should be acquired regardless of their independent predictive contribution. Beyond those, prioritize gasoline, furnace oil and house-only NHPI. Do not buy a large alternate-data bundle on the strength of this report.

## Proposed Market Watch design, not implemented

Keep three layers separate.

**Deterministic collection:** immutable raw payloads; exact source series IDs; geography; units; SA/NSA/tax status; reference period; release timestamp; ingestion timestamp; vintage; hash; collection window; revision flags; legal access terms. A series identity must not depend on a display label. Bind aliases explicitly to a Canadian canonical component ID and preserve source identifiers.

**Quantitative forecasting:** a Canadian component registry with parent ID, basket membership and effective dates, full-precision weight where available, price-index basis, model version, predictor eligibility, fallback and reliability class. Store each forecast's information set and training end date. Begin with B2. Keep meat/U.S. and aggregate-SA models as shadow challengers. Reject candidates without sustained OOS improvement, sensible economic mapping and reasonable performance in shocks. Do not optimize dozens of unstable predictors jointly.

**Human interpretation:** explain observed fuel changes, modeled travel offsets, core momentum, base effects, consensus differences and risks. This layer may annotate scenarios; it must not overwrite the numerical forecast or its evidence without a separately recorded adjustment and reason.

Suggested canonical records:

* `series`: canonical ID, source ID, source table/API, country, geography, component, unit, index base, seasonal/tax status, methodology-valid interval.
* `observation`: series ID, reference month, value, published_at, retrieved_at, vintage ID, status, source hash.
* `basket_member`: component ID, parent ID, expenditure year, link month, effective start/end, weight and precision.
* `forecast_component`: target month, as_of, model version, predicted NSA change, predictive draws, source-observed/proxy/modeled classification, fallback, training cutoff.
* `forecast_run`: immutable input manifest, aggregate NSA/index/YoY, Canadian SA bridge, core forecasts, intervals, contribution sum/residual, revision attribution.
* `release_actual`: first print and later vintages separately, plus scored errors against the frozen pre-release run and timestamped consensus.

Aggregation should use a complete non-overlapping Canadian partition and chain-link rules. Derive YoY from index levels. Keep official-core forecasting separate from a clearly named reconstructed proxy. Do not let either impersonate the other. For uncertainty, jointly resample component residuals in month blocks, preserve common fuel/travel shocks, and score coverage out of sample. Until that exists, empirical aggregate forecast-error bands are preferable to independent component minima/maxima. Report scenario bands separately from prediction intervals.

Proposed cadence: refresh public fuel/FX observations daily during the reference month; freeze the completed-month fuel panel after month-end; refresh eligible monthly predictors on their actual release; freeze a dated pre-release estimate and consensus snapshot before Canada's release. On release day, fetch official tables, validate period/units and index ratios, preserve first prints, update history, then produce contribution and surprise attribution. This is a design proposal only; no refresh job or listener has been installed.

Failure behavior should be proportionate. Missing predictors cause an explicit historical fallback and wider uncertainty; they do not erase a valid baseline. Wrong target month, inconsistent units, duplicate canonical identities, stale basket, overlapping aggregation, unavailable-after-cutoff data or an unexplained contribution residual block publication of the affected forecast. Quarantine a suspicious observation and preserve the last valid run. Large genuine gasoline/airfare moves require source corroboration, not unconditional rejection at a universal percentage threshold.

The current U.S. engine inspected is repository commit `887c93436fe8b65b2b05c04c879543de28df842c`. Its canonical identities, immutable snapshots, source registry, observation replacement, provenance, reliability labels and revision accounting are useful. Its documentation explicitly defers point-in-time backtesting and model selection; a functioning release calculator is not evidence of forecasting superiority.

The inspected CPI cache contains only July–September 2026 and the BEA component history approximately 24 months. Reuse the BLS normalization/cache mechanics and legitimate raw U.S. predictors, but acquire much longer histories for estimation. Keep Canadian weights, hierarchy, shelter methodology, tax treatment, seasonality, model selection and validation separate. Do not transfer BEA source mappings, PCE signed offsets, unit-beta PPI news bridges, U.S. seasonal factors, or the U.S. engine's last-versus-three-month scenario envelope as a Canadian confidence interval. No conclusion here requires changing the existing U.S. release process.

## Open limitations and production gate

1. No sufficiently complete, timestamped historical economist-consensus panel was obtained. **An edge over consensus remains unknown.** A current calendar number is not a historical benchmark.
2. The main backtest is not completely vintage-clean. Archive future NRCan observations and first-release CPI/PPI/NHPI data; rebuild past vintages where practical before making stronger claims.
3. The public legacy 55 mapping has a 0.81-point weight gap; tax-adjusted component inputs and exact seasonal specifications are missing. Resolve with official metadata/data access before claiming replication.
4. Core vintage data retrieved here end in April 2026. The newer revision policy has too little evaluation history for tight confidence claims.
5. Canadian fare, scanner, insurance-quote and matched vehicle-price microdata were not acquired. Their potential value is unmeasured, not zero.
6. Separate new/used Canadian vehicle histories are short. Major methodology changes, including rent, airfare, electronics and insurance, constrain long-sample comparisons.
7. Aggregate bridging is approximate. A complete disjoint Canadian leaf model, exact reconciliation and archived source-publication clocks remain production prerequisites.
8. Regime splits are diagnostics, not independently validated regime-switching models. Tariff/FX/energy interactions need a larger or prospectively accumulated sample.

The defensible next step is a small Canadian shadow engine built around the proven direct feeds and transparent fallback models, followed by frozen prospective scoring against both simple baselines and captured consensus. There is enough evidence to justify that build. There is not enough evidence to promise a durable trading edge or a tenth-perfect core forecast.

## Sources and audit files

All numerical test results are this research's calculations from the retained source inputs. The evidence ZIP contains `analyze.py`, `supplement.py`, `sa_diagnostics.py`, `finalize_analysis.py`, normalized raw inputs, captured NRCan pages, release calendars, metadata, per-month predictions and result tables. `README.md` provides execution order and caveats; `manifest.json` records file hashes. The report's tables are rounded; CSVs preserve working precision.

* **S1:** [Statistics Canada, August 2026 CPI release](https://www150.statcan.gc.ca/n1/daily-quotidien/260914/dq260914a-eng.htm) and its [index table](https://www150.statcan.gc.ca/n1/daily-quotidien/260914/t001a-eng.htm).
* **S2:** [CPI 18-10-0004-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401), [SA 18-10-0006-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000601), [weights 18-10-0007-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000701).
* **S3:** [Official basket chronology](https://www.statcan.gc.ca/en/statistical-programs/document/2301_D70_V1); [2026 basket analysis](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2026005-eng.htm).
* **S4:** [CPI Reference Paper, calculation](https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-6-eng.htm) and [weights/links](https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-8-eng.htm).
* **S5:** [CPI Reference Paper, collection](https://www150.statcan.gc.ca/n1/pub/62-553-x/2023001/chap-5-eng.htm).
* **S6:** [Shelter overview](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2023007-eng.htm); [NHPI table](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810020501).
* **S7:** [New/used vehicle methodology](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2022008-eng.htm).
* **S8:** [Air transportation methodology](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2020001-eng.htm).
* **S9:** [Insurance methodology, April 2025](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2025002-eng.htm).
* **S10:** [Cellular services methodology](https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2024005-eng.htm); [official methodology index](https://www.statcan.gc.ca/en/statistical-programs/document/2301_D71_V1).
* **S11:** [BLS September CPI](https://www.bls.gov/news.release/archives/cpi_10142026.htm), [September PPI](https://www.bls.gov/news.release/archives/ppi_10152026.htm), [CPI bulk files](https://download.bls.gov/pub/time.series/cu/), [PPI bulk files](https://download.bls.gov/pub/time.series/wp/).
* **S12:** [Federal fuel-excise relief extension](https://www.canada.ca/en/treasury-board-secretariat/news/2026/09/the-government-of-canada-extends-the-federal-fuel-excise-tax-relief-on-gasoline-diesel-and-aviation-fuels-for-canadians.html).
* **S13:** [Canadian counter-tariff product lists](https://www.canada.ca/en/department-finance/programs/international-trade-finance-policy/canadas-response-us-tariffs/complete-list-us-products-subject-to-counter-tariffs.html).
* **S14:** [Core methodology](https://www.statcan.gc.ca/en/statistical-programs/document/2301_D64_T9_V3); [published index-level enhancement](https://www.statcan.gc.ca/en/statistical-programs/document/2301_D69_V1).
* **S15:** [Core statistics 18-10-0256-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810025601); [real-time releases 18-10-0259-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810025901).
* **S16:** [Bank of Canada, Underlying inflation: Separating the signal from the noise](https://www.bankofcanada.ca/wp-content/uploads/2025/10/remarks-021025.pdf).
* **S17:** [Bank of Canada lending rates and methodology](https://www.bankofcanada.ca/rates/banking-and-financial-statistics/interest-rates-for-new-and-existing-lending-by-chartered-banks/); [10-10-0006-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1010000601); [release calendar](https://www150.statcan.gc.ca/n1/dai-quo/cal2-eng.htm).
* **S18:** Trading Economics public calendars: [headline MoM](https://tradingeconomics.com/canada/inflation-rate-mom), [headline YoY](https://tradingeconomics.com/canada/inflation-cpi), [trim](https://tradingeconomics.com/canada/cpi-trimmed-mean), [median](https://tradingeconomics.com/canada/cpi-median). Retrieved October 17; secondary consensus source, not predictor input.
* **S19:** [StatCan retail prices, August, released October 7](https://www150.statcan.gc.ca/n1/daily-quotidien/261007/dq261007a-eng.htm); [food-price hub](https://www.statcan.gc.ca/en/topics-start/food-price).
* **S20:** [Canadian Black Book archive](https://www.canadianblackbook.com/market-insights/); [Cox/Manheim September index](https://www.coxautoinc.com/insights/manheim-used-vehicle-value-index-september-2026-trends/).
* **S21:** [Rentals.ca national rent report](https://rentals.ca/national-rent-report).