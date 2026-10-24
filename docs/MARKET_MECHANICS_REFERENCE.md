# Market Mechanics Reference

Canonical path: `docs/MARKET_MECHANICS_REFERENCE.md`  
Version: 1.0 | Research/access cutoff: **2026-10-02 (UTC)** | Status: baseline documentation; no agent integration

This document supplies neutral instrument mechanics for selective retrieval. It contains no current market view, position inventory, trader personality, house trading preference or experiential trading lesson. Examples are hypothetical and exclude costs unless stated. It is not an exhaustive contract catalogue.

## Retrieval and evidence conventions

Each `<!-- MMR ... -->` block immediately precedes one retrievable subsection. `id` is the stable key; dotted names identify domain and concept. Tags use lowercase kebab-case values. `asset_classes` uses only `cross-asset`, `fx`, and `rates`; `cross-asset` means applicable across asset classes, not a particular product. `instrument_families` and `concepts` are the explicit controlled values appearing in this document. `source_ids` identifies source-register records to accompany the chunk. IDs are authoritative; titles may change. Do not infer a sign from a tag.

A section ends at the next MMR marker or `<!-- MMR-END -->`. Retrieve its complete text, including qualifications and source IDs. Resolve source IDs against the source register in this same document. The audit is supporting provenance, not a competing mechanics source. No external index or retrieval code is supplied.

**Evidence labels:** “Enduring” means a definition or identity under its stated assumptions, not that every convention is universal. “Product-specific” facts were verified on the stated date and require the current rulebook before use. “Derived” identifies arithmetic or logical consequences worked out here from cited mechanics. Conduct recommendations remain attributed guidance. A public URL is not a licence to reproduce a source.

**Notation:** unless a section says otherwise, rates inside valuation equations are decimals, price quotes and multipliers retain their contract units, and positive bond DV01 is a magnitude used with `ΔV ≈ −DV01 × Δyield_bp`. Each FX formula declares quote orientation. Dollar examples mean USD. Full source metadata and limitations follow the retrieval sections.

## Retrievable mechanics

<!-- MMR
id: meta.baseline-experience
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [scope, baseline, experience]
source_ids: [S16, S23, S04]
-->
### Baseline mechanics and experiential learning

**What this establishes:** The reference supplies instrument knowledge; it does not select trades.

Baseline mechanics includes contract cash flows, quote directions, valuation identities, settlement rules and explicitly qualified risk approximations. A failure to apply one of these is a candidate baseline-mechanics failure.

Experiential learning concerns context-dependent decisions: expression selection, timing, reaction-function interpretation, regime assessment, sizing judgment and recurring decision patterns. A new experience does not alter a contract identity. Conversely, knowing the identity does not establish that a particular trade is attractive.

This boundary is an editorial classification for this reference, not a market theorem. Source-backed examples are the contract rules and risk definitions cited below. Trader memories, personalities, portfolio holdings and house preferences are not evidence here. Attributed conduct guidance is identified as such; hypothetical calculations are not recommendations.

**Scope/currentness:** Editorial scope; cited sources illustrate mechanics rather than prescribe this classification.

**Sources:** [S16](#source-s16), §§46001–46003; [S23](#source-s23), §§98.18–19 and 98.42–44; [S04](#source-s04), Foreword.

<!-- MMR
id: shared.units
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [basis-points, units, percentages]
source_ids: [S46, S16, S42]
-->
### Basis points, percentages and quote units

**What this establishes:** A number needs its measurement unit before its direction or P&L can be interpreted.

One basis point (bp) is 0.01 percentage point, or 0.0001 in decimal-rate units. A rate moving from 4% to 5% rises 100 bp, one percentage point, and 25% relative to its initial level. These descriptions are not interchangeable.

A price point, tick, pip and volatility point refer to different quote scales. In a 100-minus-rate future, a one-bp rate fall raises the quoted index by 0.01, not by 1. Contract currency P&L also requires the multiplier. A one-volatility-point move is, for example, 20% to 21% volatility.

Use decimal yield changes in calculus formulas unless the formula explicitly says bp. Keep price per 100 face, currency market value, and per-contract dollars separate.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S46](#source-s46), Basis Points entry; [S16](#source-s16), §46002.B–C; [S42](#source-s42), vega units; arithmetic identities derived here.

<!-- MMR
id: shared.direction
asset_classes: [cross-asset]
instrument_families: [cash-bonds, futures, swaps]
concepts: [direction, receive-fixed, pay-fixed, quote-sign]
source_ids: [S35, S12, S32, S16]
-->
### Long, short, receive and pay

**What this establishes:** Position labels refer to a specified contract or cash-flow leg.

For a linear price-quoted contract, a long gains when its quoted price rises; a short gains when it falls. Long a conventional fixed-rate bond usually gains when its yield falls. Long a 100-minus-rate STIR future gains when its implied rate falls. Long a yield-quoted future gains when its quoted yield rises.

In a fixed-versus-floating rates swap, “receive” conventionally means receive fixed/pay floating; “pay” means pay fixed/receive floating. State the leg explicitly. With conventional cash flows and other valuation inputs fixed, receiving fixed benefits from lower comparable forward rates. Receiving a currency in an FX swap does not mean receiving fixed interest.

“Long rates” and “receive the strip” are desk shorthand, not complete trade specifications. Name the instrument, side, benchmark and maturities.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S35](#source-s35), Long/Short entries; [S12](#source-s12), OIS instruments; [S32](#source-s32), yield quotation; [S16](#source-s16), §46002.C.

<!-- MMR
id: shared.notional-risk
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [notional, dv01, delta, leverage]
source_ids: [S02, S19, S23, S44]
-->
### Notional, market value and risk units

**What this establishes:** Equal notionals do not establish equal economic exposure.

Notional scales contractual cash flows; market value is the current value of a position. Either can differ greatly from posted collateral and from loss under a stated shock. A par swap may have near-zero initial value but substantial rate sensitivity.

Risk units specify both a factor and a currency: for example USD per bp of a yield-curve shift, or USD per unit change in an FX quote. Options also require nonlinear and volatility sensitivities. A matched-notional pair can retain large net DV01. A matched-DV01 pair can retain curve, basis, convexity and currency risk.

Turnover is a flow measured over a period; outstanding notional is a stock at a date. Neither is a direct measure of net market risk or capital at risk.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S02](#source-s02), survey reporting basis; [S19](#source-s19), equivalent notional; [S23](#source-s23), §§98.42–44; [S44](#source-s44), model sensitivities.

<!-- MMR
id: shared.valuation
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [mark-to-market, realized-pnl, unrealized-pnl]
source_ids: [S23, S34, S04]
-->
### Mark-to-market and realized versus unrealized P&L

**What this establishes:** Economic valuation, cash settlement and accounting recognition are distinct.

Mark-to-market values remaining contractual rights and obligations at current market inputs. An unrealized gain is a valuation gain not yet recognized as realized under the applicable accounting convention. Realization can occur through sale, expiry or settlement; recognition rules differ.

Futures variation settlement transfers gains and losses in cash while the position remains open. Closing the position is not required for those cash movements. An OTC derivative may retain a marked value while collateral moves separately. Settled-to-market and collateralized-to-market arrangements require different cash-flow bookkeeping.

For economic P&L, count changes in remaining value and net attributable cash flows exactly once. A bank’s accounting income need not equal the change in its economic value. A displayed mid quote also need not be an executable liquidation price.

**Scope/currentness:** Valuation principle is enduring; accounting, collateral treatment and mark policies are agreement-specific.

**Sources:** [S23](#source-s23), §§98.3–6; [S34](#source-s34), marking-to-market discussion; [S04](#source-s04), Execution.

<!-- MMR
id: shared.time
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [dates, maturity, fixing, holding-period]
source_ids: [S15, S16, S33, S22]
-->
### Trade date, value date, fixing, expiry and horizon

**What this establishes:** Different dates answer different mechanical questions.

Trade date records agreement; value/settlement date records the contracted exchange of cash or securities. A fixing date or observation window determines a floating payment or cash settlement. Last trading time, option expiry, futures delivery month and final settlement can differ.

Maturity is the contractual endpoint of specified cash flows. Remaining maturity decreases with time. Duration is a sensitivity or weighted cash-flow measure, not simply maturity. A holding period is how long a position is actually retained; it can end well before maturity.

Business-day adjustment, holiday calendars, day count, time zone and publication lag can change the relevant interval. Month labels alone are insufficient: an SR3 named month identifies the start of its reference quarter, whereas the rulebook’s delivery month is at its end.

**Scope/currentness:** Date vocabulary is enduring; actual dates are product- and calendar-specific, verified from current specifications.

**Sources:** [S15](#source-s15), contract naming; [S16](#source-s16), §46003.A.1; [S33](#source-s33), §4 lifecycle; [S22](#source-s22), duration definitions.

<!-- MMR
id: fx.spot.quotes
asset_classes: [fx]
instrument_families: [spot, forwards, futures]
concepts: [quotation, base-currency, terms-currency, appreciation]
source_ids: [S06]
-->
### Base currency, terms currency and appreciation

**What this establishes:** Quote orientation determines both direction and conversion arithmetic.

Define S as units of terms currency T per one unit of base currency B. In EUR/USD, EUR is base and USD is terms. If S rises, the base appreciates against the terms currency. The reciprocal quote falls; percentage changes in reciprocal quotes are not exactly equal and opposite for finite moves.

Buying B/T means buying B and selling T. For an unchanged amount N of base currency, its terms-currency valuation change is N × (S_new − S_old). Funding and other cash flows are separate. A dealer bid is the price at which that dealer buys base; the ask is where it sells base.

Some FX futures use a quote orientation different from common OTC spot notation. A currency ticker or “buy dollars” alone does not define a pair or exposure.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S06](#source-s06), quote conventions; reciprocal and valuation arithmetic derived here.

<!-- MMR
id: fx.spot.value-dates
asset_classes: [fx]
instrument_families: [spot, forwards, fx-swaps]
concepts: [settlement-date, calendars, spot-lag]
source_ids: [S01, S04, S08]
-->
### Spot value dates and broken dates

**What this establishes:** Spot is a settlement convention, not a synonym for same-day delivery.

Many wholesale FX pairs conventionally settle two business days after trade date; exceptions exist. The actual spot date depends on the currency pair, relevant settlement calendars, holidays and cutoffs. Same-day, next-day and non-standard dates require the appropriate agreement and pricing.

Forward tenor is commonly measured from the spot date. Comparing a cash rate beginning today with a forward beginning on the spot date without adjusting the initial interval can introduce a financing mismatch. A securities settlement date does not automatically change an FX pair’s spot convention.

This reference deliberately contains no universal pair-by-pair calendar. A transaction’s confirmed value date governs its cash obligation. Holiday conventions and operational deadlines require fresh verification.

**Scope/currentness:** Convention-dependent; broad T+2 description checked 2026-10-02, not an exhaustive settlement calendar.

**Sources:** [S01](#source-s01), settlement discussion; [S04](#source-s04), Confirmation and Settlement; [S08](#source-s08), dated forward construction.

<!-- MMR
id: fx.market.structure
asset_classes: [fx]
instrument_families: [spot, forwards, fx-swaps]
concepts: [dealer, interdealer, otc, execution-venue]
source_ids: [S02, S03, S01]
-->
### Dealers, clients, venues and current FX structure

**What this establishes:** Wholesale FX remains OTC but is not a single voice-based interbank market.

Dealers transact with customers and with other liquidity providers; they may offset risk externally or match customer flows internally. Electronic request-for-quote systems, single-dealer platforms, order books, voice execution and other methods coexist. Non-bank liquidity providers and principal trading firms also participate.

Access, credit relationships, execution protocol and available liquidity differ across venues and participants. A price observed on one venue need not be available for another participant’s size, credit relationship or settlement terms. Interdealer turnover does not equal end-client demand.

The 2025 BIS Triennial Survey modernizes older dealer-market descriptions. Its turnover classifications and execution shares describe the survey period. No enduring identity depends on those shares remaining constant.

**Scope/currentness:** Market-structure description verified 2026-10-02 using 2025 survey research; reassess as structure changes.

**Sources:** [S02](#source-s02), counterparties and instruments; [S03](#source-s03), execution methods and internalisation; [S01](#source-s01), market evolution.

<!-- MMR
id: fx.market.execution
asset_classes: [fx]
instrument_families: [spot, forwards, fx-swaps]
concepts: [principal, agent, last-look, confidentiality]
source_ids: [S04]
-->
### Execution roles and information handling

**What this establishes:** Execution terms and professional conduct guidance are distinct from expected returns.

A principal deals for its own account; an agent executes on a client’s behalf under an agreed mandate. Their obligations, pricing arrangements and conflicts differ. A request, indicative quote, executable quote and completed trade are distinct states. Acceptance conditions, including any last-look process, depend on disclosed venue or counterparty terms.

The FX Global Code offers voluntary principles on role disclosure, execution, confidential information, confirmation and settlement. These are attributed conduct expectations, not laws asserted by this reference and not signals for market direction. Confidential order information is not interchangeable with public market information.

Mechanical analysis identifies the actual execution price, size, fees, rejection conditions and settlement obligation. Conduct principles do not establish that a strategy has positive expected P&L.

**Scope/currentness:** Attributed guidance: December 2024 FX Global Code; actual legal and contractual obligations vary.

**Sources:** [S04](#source-s04), Foreword; Execution; Information Sharing; Confirmation and Settlement.

<!-- MMR
id: fx.settlement.risk
asset_classes: [fx]
instrument_families: [spot, forwards, fx-swaps]
concepts: [settlement-risk, pvp, netting, counterparty-risk]
source_ids: [S05, S04]
-->
### Principal settlement risk and payment-versus-payment

**What this establishes:** Settlement exposure can involve the full currency principal, not just a mark-to-market loss.

Principal risk arises when one currency has been irrevocably paid before receipt of the other is assured. It differs from replacement-cost exposure on an unsettled trade’s positive market value. Time-zone and payment-system differences can affect the exposure interval.

Payment-versus-payment (PvP) links the two final transfers so that one occurs only if the other occurs, eliminating the principal settlement risk within that arrangement. It does not eliminate every funding, operational or replacement-cost risk. Netting can reduce amounts requiring payment without necessarily eliminating the remaining principal risk.

PvP coverage is not universal across currencies, counterparties and products. The Global Code’s preference for eliminating or reducing settlement risk is attributed conduct guidance. Eligibility and actual settlement arrangements must be identified for the trade.

**Scope/currentness:** Risk distinction is enduring; service coverage and settlement arrangements are current, product-specific facts.

**Sources:** [S05](#source-s05), settlement-risk measures and mitigation; [S04](#source-s04), Principle 35.

<!-- MMR
id: fx.forwards.outrights
asset_classes: [fx]
instrument_families: [forwards]
concepts: [outright, forward-rate, mark-to-market]
source_ids: [S07, S08]
-->
### Outright forwards and their value

**What this establishes:** A forward fixes a future exchange rate; it does not fix the future market value of the contract.

A deliverable outright forward agrees an exchange of specified currency amounts at a future value date. Define B as base, T as terms and K as the agreed T-per-B rate. A buyer of N base pays N × K terms on settlement. A par forward can begin with approximately zero value without being riskless or without future collateral requirements.

Under consistent collateral/discounting assumptions, the terms-currency value of that long-base forward before settlement is approximately N × DF_T × (F_current − K), where F_current is the market forward for the same value date. This is a replication result, not a universal accounting mark for every agreement.

Changing spot, either discount curve, cross-currency basis or remaining maturity can change value. Comparing K only with today’s spot omits the remaining financing interval.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S07](#source-s07), covered replication; [S08](#source-s08), forward construction; valuation equation derived under stated assumptions.

<!-- MMR
id: fx.forwards.points
asset_classes: [fx]
instrument_families: [spot, forwards, fx-swaps]
concepts: [forward-points, pips, outright]
source_ids: [S08, S06]
-->
### Forward points and spot-plus-points

**What this establishes:** Forward points are a quote difference with a specified scale.

With both quotes in terms currency per base currency, define points p = F − S. The outright forward is F = S + p after converting displayed points into the same units as spot. Pip multipliers differ by pair and venue; never add an unscaled screen number to spot.

Hypothetical arithmetic: S = 1.1000 and points = +0.0025 imply F = 1.1025. If the display unit is 0.0001, the displayed points are +25. Negative points imply F below S in this orientation. Inverting the currency pair changes the relation nonlinearly; simply negating displayed points is not exact.

Bid/ask points and executable outright rates require the provider’s quote construction. A negative forward premium is not itself a prediction of base-currency depreciation.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S08](#source-s08), swap-point construction; [S06](#source-s06), quote conventions; numeric example derived here.

<!-- MMR
id: fx.forwards.parity
asset_classes: [fx, rates]
instrument_families: [forwards, fx-swaps]
concepts: [covered-interest-parity, interest-differential, basis]
source_ids: [S07]
-->
### Covered interest parity and cross-currency basis

**What this establishes:** Relative financing costs link spot and forward rates under specified replication assumptions.

Let S and F be T currency per B currency. For the same start/end dates and frictionless simple funding rates, F = S × (1 + r_T × τ_T) / (1 + r_B × τ_B). Rates are decimals; each τ follows its currency’s day count. Equivalently F = S × DF_B / DF_T for consistent discount factors.

For equal one-year accruals, S = 1.10, r_T = 5% and r_B = 3% give F ≈ 1.12136. Higher terms-currency interest rates therefore imply positive points in this convention, all else equal.

Observed funding access, collateral terms, balance-sheet constraints and currency demand can produce a nonzero cross-currency basis relative to chosen benchmark curves. A basis quote needs its benchmark, leg and sign convention. The simple equality is a conditional replication benchmark, not a claim that observed basis must always be zero.

**Scope/currentness:** Conditional identity; benchmark curves, day counts and basis quotation are convention-dependent.

**Sources:** [S07](#source-s07), CIP relationship and deviations; numeric example is this reference’s derivation.

<!-- MMR
id: fx.forwards.carry
asset_classes: [fx]
instrument_families: [forwards, futures]
concepts: [carry, forecast, funding]
source_ids: [S09, S07, S34]
-->
### FX carry and why forwards are not spot forecasts

**What this establishes:** The forward premium reflects financing relationships, not a mechanical prediction of future spot.

At settlement, a long-base forward’s terms-currency payoff relative to exchanging at prevailing spot is N × (S_T − K). This payoff formula contains the contracted forward K, not only the initial spot. Spot can move in the anticipated direction while the position still loses relative to K.

Under an unchanged-spot scenario, the forward’s terminal payoff is N × (S_0 − K). That scenario exposes the interest-differential component often called FX carry. It is conditional: future spot, basis, funding and costs can offset it.

A futures price and an OTC forward can differ because daily settlement, collateral and funding differ. Neither should be treated as an unadjusted statistical expectation of future spot. “High yielding currency” alone does not determine total return in a reporting currency.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S09](#source-s09), spot/futures reconciliation; [S07](#source-s07), covered relationship; [S34](#source-s34), daily settlement; payoff/scenario algebra derived here.

<!-- MMR
id: fx.swaps.legs
asset_classes: [fx]
instrument_families: [fx-swaps]
concepts: [near-leg, far-leg, funding, rollover]
source_ids: [S08, S05]
-->
### FX swaps and currency funding

**What this establishes:** An FX swap combines opposite currency exchanges on two value dates.

An FX swap agrees a near-date exchange and its reverse on a later date, with both rates fixed at inception. Buying base near and selling base far obtains base-currency funding over the interval against the terms currency; the reverse direction supplies base currency and obtains terms currency. Actual notionals and forward points determine cash flows.

Spot-starting, overnight, tomorrow-next and forward-starting swaps differ in their value dates. An FX swap is not the same as a cross-currency interest-rate swap, which can include periodic interest payments and separate principal-exchange conventions.

The two legs reduce some outright FX exposure compared with an unhedged currency holding, but leave financing, basis, counterparty and settlement exposures. Rolling a swap replaces the expiring funding interval at then-available prices; the original points do not lock future rolls.

**Scope/currentness:** Two-leg structure is enduring; calendars, notionals, collateral and rollover prices are contract-specific.

**Sources:** [S08](#source-s08), FX swaps and forward-forward discussion; [S05](#source-s05), settlement mechanics.

<!-- MMR
id: fx.ndf.settlement
asset_classes: [fx]
instrument_families: [ndf]
concepts: [fixing, cash-settlement, offshore, basis]
source_ids: [S10]
-->
### Non-deliverable forwards

**What this establishes:** An NDF settles a rate difference without exchanging both currency principals.

An NDF specifies a notional, contracted exchange rate, fixing source/time, settlement currency and payment date. Its net payment depends on the difference between the contract rate and the designated fixing. The exact formula depends on quote orientation and which currency defines the notional; the deliverable-forward formula cannot be copied without those details.

The fixing date can precede payment. The fixing may differ from an executable conversion rate for the underlying commercial exposure, leaving fixing or basis risk. Offshore NDF pricing can diverge from onshore deliverable forwards where market access, convertibility or capital restrictions differ.

Cash settlement does not eliminate counterparty, collateral or payment risk. A deliverable CIP calculation is not automatically an executable arbitrage across a restricted currency boundary.

**Scope/currentness:** Enduring structure; currency restrictions, fixing definitions and settlement formulas require current product documentation.

**Sources:** [S10](#source-s10), NDF definition and onshore/offshore segmentation.

<!-- MMR
id: rates.benchmarks.overnight
asset_classes: [rates]
instrument_families: [money-market, ois, stir-futures]
concepts: [policy-rate, sofr, effr, overnight]
source_ids: [S11, S14]
-->
### Policy rates and overnight benchmarks

**What this establishes:** A central-bank policy setting is not identical to every traded overnight rate.

A policy rate can be an administered rate, a target or a target range. An overnight benchmark measures transactions under a defined methodology. EFFR reflects unsecured federal-funds activity; SOFR reflects secured overnight Treasury repo activity. Their levels need not equal each other or a target-range endpoint.

Publication follows the observation period and can involve non-business-day treatment. A displayed latest fixing is backward-looking for that observation date. Future benchmark exposures depend on future fixings, not on an assumption that today’s published rate persists.

Benchmarks vary by currency and contract. Overnight risk-free-rate derivatives coexist with some reformed term benchmarks; the transition away from LIBOR did not make every STIR future a SOFR future.

**Scope/currentness:** Definitions endure; benchmark methodology and policy frameworks verified as of 2026-10-02 and subject to change.

**Sources:** [S11](#source-s11), EFFR/SOFR methodology and publication; [S14](#source-s14), benchmark transition.

<!-- MMR
id: rates.ois.cashflows
asset_classes: [rates]
instrument_families: [ois]
concepts: [receive-fixed, pay-fixed, compounding, notional]
source_ids: [S12]
-->
### OIS cash flows and receive/pay direction

**What this establishes:** An overnight indexed swap exchanges fixed interest against an overnight-rate-based leg.

A conventional OIS exchanges fixed interest with interest accumulated from an overnight benchmark, typically compounded. Same-currency principal is generally a calculation notional rather than an amount exchanged. Payment frequency, day count, observation shifts, lookbacks and payment lags follow the agreement.

For a simplified single payment period, receiver-fixed cash flow is N × [K × α − (A − 1)], where K is a decimal fixed rate, α its accrual fraction and A the floating accumulation factor. Payer-fixed has the opposite cash flow.

For the same contract with fixed K, lower future overnight fixings reduce the receiver’s floating payments. This is the receive-fixed direction. Receiving fixed does not mean receiving every leg, and the swap’s fixed rate is not necessarily the central bank’s policy rate on its final date.

**Scope/currentness:** Standard OIS structure; exact cash-flow conventions are agreement-specific.

**Sources:** [S12](#source-s12), OIS instrument description; single-period cash-flow equation derived here.

<!-- MMR
id: rates.ois.valuation
asset_classes: [rates]
instrument_families: [ois, money-market]
concepts: [par-rate, discount-factor, forward-rate, convexity-adjustment]
source_ids: [S12, S13, S45]
-->
### OIS par rates, discounting and forward rates

**What this establishes:** A par swap rate balances discounted legs; it is not an unweighted list of future policy decisions.

For fixed payment dates i, fixed-leg PV is N × K × Σ(α_i × DF_i). The par K makes this equal the floating-leg PV. In a simplified single-curve, spot-starting arrangement without payment lags, floating PV is N × (DF_start − DF_end). Real implementations respect projection, collateral and payment conventions.

A forward simple rate over dates a,b satisfies 1 + f × α = DF_a / DF_b under the chosen curve. Spot/zero rates discount individual dates; par rates price whole coupon schedules. They are not interchangeable numbers.

Futures-implied rates and forward/OIS rates need not coincide because settlement timing and rate variability matter. Risk and term premia also complicate inference about expected policy. Extracting a path requires a model and stated conventions, not just relabeling a quote.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S12](#source-s12), spot/forward/par definitions; [S13](#source-s13), policy-expectation measurement; [S45](#source-s45), payout differences; equations derived for stated simplified cash flows.

<!-- MMR
id: rates.futures.stir
asset_classes: [rates]
instrument_families: [stir-futures]
concepts: [100-minus-rate, long, short, bpv]
source_ids: [S16, S14, S32]
-->
### STIR futures: price direction and benchmark scope

**What this establishes:** A long 100-minus-rate future benefits from a lower contract-implied rate.

For a contract quoted Q = 100 − R, R is expressed in percent per annum. Thus ΔQ = −ΔR in percentage-point units. Long-contract P&L is multiplier × ΔQ; short-contract P&L has the opposite sign.

Hypothetical SR3 example: buying at 95.00 and selling at 95.20 gains 0.20 × USD 2,500 = USD 500 per contract before costs. The implied rate fell from 5.00% to 4.80%, or 20 bp. “Receiving” a futures strip is shorthand for this lower-rate exposure, not a literal swap coupon receipt.

Identify the benchmark and fixing window. A term-deposit future, overnight-average future and compounded-overnight future can have different credit, timing and compounding exposures. Yield-quoted futures reverse the familiar 100-minus-rate price direction.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S16](#source-s16), §§46001 and 46002.C; [S14](#source-s14), benchmark differences; [S32](#source-s32), yield futures; arithmetic derived here.

<!-- MMR
id: rates.sofr.sr3
asset_classes: [rates]
instrument_families: [sofr-futures]
concepts: [sr3, compounding, reference-quarter, settlement]
source_ids: [S16, S15]
-->
### Three-Month SOFR futures: reference quarter and settlement

**What this establishes:** SR3 settles to compounded realized SOFR over its defined reference quarter.

Verified as of 2026-10-02: SR3 uses Q = 100 − R and USD 2,500 per index point, hence USD 25 per bp of quoted contract rate. The named contract month starts the reference quarter: normally third Wednesday inclusive to third Wednesday three months later exclusive. Final settlement follows the rulebook.

With daily published rates r_i in percent, calendar-day weights d_i, and D = Σd_i:

R = 100 × {Π[1 + (r_i / 100) × d_i / 360] − 1} × 360 / D.

Weekend/holiday intervals apply the relevant preceding business-day rate over their calendar days according to the rule. SR3 is cash settled. It does not deliver a three-month loan, and its quoted rate is not simply the last overnight fixing or the arithmetic mean of daily rates.

**Scope/currentness:** Product-specific facts verified 2026-10-02; current Chapter 460 controls.

**Sources:** [S16](#source-s16), §§46001–46003.A; [S15](#source-s15), naming and reference-period examples.

<!-- MMR
id: rates.sofr.sr1
asset_classes: [rates]
instrument_families: [sofr-futures]
concepts: [sr1, averaging, settlement, bpv]
source_ids: [S17, S16]
-->
### One-Month SOFR futures: arithmetic averaging

**What this establishes:** SR1 and SR3 use different averaging and risk multipliers.

Verified as of 2026-10-02: SR1 quotes 100 minus calendar-month average daily SOFR, weighted by the calendar days to which each fixing applies. The settlement rate is an arithmetic average, not SR3’s annualized compounded quarterly rate.

Chapter 461 defines USD 4,167 per index point and USD 41.67 per bp per contract. Use the specified multiplier rather than assuming every short-rate contract has USD 25 BPV. Published rulebook precision and final-settlement rounding govern cash amounts.

A monthly contract can contain days before and after a policy meeting. Its implied average is not the post-meeting rate. Once some daily rates have fixed, inference about the remaining days must remove those known contributions. Matching an SR1 position to SR3 requires both date-window and risk weighting.

**Scope/currentness:** Product-specific facts verified 2026-10-02; current Chapter 461 controls.

**Sources:** [S17](#source-s17), §§46101–46103; contrast with [S16](#source-s16), §46003.A.

<!-- MMR
id: rates.sofr.fixings
asset_classes: [rates]
instrument_families: [sofr-futures, ois]
concepts: [realized-fixing, implied-path, residual-sensitivity]
source_ids: [S18]
-->
### Known fixings and remaining rate exposure

**What this establishes:** An in-progress averaging contract combines facts already fixed with future exposure.

For arithmetic averaging, total average × total day count equals known weighted fixings plus the remaining implied weighted sum. For compounded SR3, divide the full implied accumulation factor by the product of already-known daily factors to obtain the remaining implied accumulation factor. Do not subtract compounded rates as if they were simple sums.

Example using arithmetic averaging only: a 30-day period priced at 5.00%, with 15 days fixed at 4.00%, implies a 6.00% average for the remaining 15 days, ignoring premia and conventions. It does not imply all 30 days will fix at 5.00%.

The contract’s currency value per bp of its quoted rate remains specified, but sensitivity to a one-bp change in only the unfixed days declines as days fix. Historical fixings cannot respond to a later policy surprise.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S18](#source-s18), “In general” equations and known-fixing examples; arithmetic example derived here.

<!-- MMR
id: rates.strips.cash-path
asset_classes: [rates]
instrument_families: [stir-futures, sofr-futures, ois]
concepts: [policy-path, above-cash, below-cash, tightening, easing]
source_ids: [S20, S13, S16]
-->
### A strip above or below current cash

**What this establishes:** Direction is measured against the priced future benchmark path, not just today’s cash rate.

A strip is a set of contracts spanning specified future periods. If their implied benchmark rates exceed current comparable overnight cash, pricing embeds higher future period rates relative to that cash observation, subject to compounding, benchmark basis and premia. Below-cash pricing embeds the reverse comparison. Neither is a guaranteed sequence of policy decisions.

Illustrative single-period arithmetic: cash is 4%, a future implies 5%, and a trader buys that 100-minus-rate future. This is exposure benefiting from less tightening/lower rates than the 5% price, even though cash could rise. Settlement at 4.75% gains 25 bp of contract price; settlement at 5.25% loses 25 bp. Settlement unchanged at the entry-implied 5% gives zero cumulative price P&L before costs and funding.

Calling the position “defensive” does not change this direction. A slowdown narrative and a fade of priced tightening can describe the same exposure; mechanics alone cannot establish its attractiveness.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S20](#source-s20), strip construction; [S13](#source-s13), limits of policy inference; [S16](#source-s16), quote identity; scenarios derived here.

<!-- MMR
id: rates.strips.risk
asset_classes: [rates]
instrument_families: [stir-futures, sofr-futures, ois]
concepts: [strip, hedge-ratio, bpv, equivalent-notional]
source_ids: [S19, S20, S12]
-->
### Strip weighting and cash-versus-strip comparisons

**What this establishes:** A strip’s exposure is the sum of dated contract sensitivities, not a headline notional.

For signed quantities q_j and quoted-rate BPV b_j, first-order price P&L for 100-minus-rate contracts is −Σ(q_j × b_j × ΔR_j,bp). Equal contract counts are equal quoted-rate BPV only where multipliers match. They need not imply equal sensitivity to an individual meeting or a parallel shift in still-unfixed daily rates.

SR3’s USD 25 per quoted bp corresponds approximately to a simple-rate notional N = 25 / (0.0001 × D/360). At D = 90 days, N = USD 1 million; at 91 days, about USD 989,011. This is an equivalent sensitivity, not delivered principal.

Comparing a cash loan, futures strip and OIS requires aligned benchmarks, start/end dates, day counts, compounding, discounting and settlement funding. An arithmetic mean of futures-implied rates is not automatically the matching OIS par rate.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S19](#source-s19), contract notional; [S20](#source-s20), strip construction; [S12](#source-s12), par-rate concepts; weighting algebra derived here.

<!-- MMR
id: bonds.cashflows.price-yield
asset_classes: [rates]
instrument_families: [government-bonds, bills]
concepts: [coupon, price, yield, accrued-interest]
source_ids: [S21, S46]
-->
### Bond cash flows, clean price and dirty price

**What this establishes:** A fixed coupon schedule and the price paid are separate inputs to return.

A conventional fixed-rate bond promises coupons and principal on specified dates. Coupon rate applies to face value; it is not the yield earned at every purchase price. For discount factors DF_i and contractual cash flows CF_i, full price P_dirty = Σ(CF_i × DF_i).

Where clean-price quotation applies, dirty price = clean price + accrued interest. Settlement cash uses the appropriate full price and face amount. Accrued interest treatment, ex-coupon periods and quotation conventions vary by sovereign and market.

With fixed positive cash flows, higher discount rates reduce present value, all else equal. US Treasury notes and bonds normally pay semiannual coupons; that frequency is not universal. Bills are typically issued/traded at a discount, and a bank-discount quote based on face value and a 360-day denominator is not the investor’s price-based holding-period yield.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S21](#source-s21), bills and notes/bonds; [S46](#source-s46), accrued interest and bond pricing; discounted-cash-flow identity stated here.

<!-- MMR
id: bonds.yield.interpretation
asset_classes: [rates]
instrument_families: [government-bonds]
concepts: [ytm, reinvestment, current-yield, discounting]
source_ids: [S21, S46, S23]
-->
### Yield to maturity and its limits

**What this establishes:** YTM is a price-equivalent internal rate, not a guaranteed realized total return.

Yield to maturity is the single rate that discounts contractual cash flows to the full price under a chosen compounding convention. For regular m-times-yearly periods, P = Σ CF_k / (1 + y/m)^k; irregular periods require the market’s timing rules.

Current yield is annual coupon divided by price; it omits redemption gain/loss. The YTM calculation itself requires no forecast of reinvestment. Accumulating terminal wealth at that compound rate requires the relevant cash flows to occur and interim receipts to earn the equivalent reinvestment return. Selling early introduces the future exit price. Default, options and inflation can alter the economic interpretation.

Yields quoted with different day counts, compounding or maturity structures are not automatically comparable. A price-implied yield also does not separately identify expected short rates, term premium, credit or liquidity compensation.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S21](#source-s21), pricing/yield discussion; [S46](#source-s46), Current Yield and early sale; [S23](#source-s23), §98.7 rate components; IRR/terminal-wealth distinction derived here.

<!-- MMR
id: bonds.risk.duration
asset_classes: [rates]
instrument_families: [government-bonds]
concepts: [duration, modified-duration, effective-duration]
source_ids: [S22, S25]
-->
### Macaulay, modified and effective duration

**What this establishes:** Duration summarizes local rate sensitivity under specified assumptions.

For positive fixed cash flows, Macaulay duration is the present-value-weighted average payment time. With m-period compounding, modified duration D_mod = D_Mac / (1 + y/m). For a small change in decimal yield, ΔP/P ≈ −D_mod × Δy.

Modified duration is therefore a slope measure, not the bond’s maturity or an exact forecast for a large yield move. Effective duration revalues the instrument under specified curve shocks and can incorporate changing cash flows from embedded options. Key-rate duration allocates sensitivity to curve locations rather than assuming a single parallel move.

The measure depends on current price, yield, cash flows and the chosen shock. A short bond position reverses the long position’s first-order P&L sign; duration reported as an unsigned instrument statistic does not by itself identify portfolio direction.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S22](#source-s22), duration types and limitations; [S25](#source-s25), Duration; formulas are derivatives of the fixed-cash-flow price identity.

<!-- MMR
id: bonds.risk.dv01
asset_classes: [rates]
instrument_families: [government-bonds, swaps, futures]
concepts: [dv01, pv01, bpv, signed-risk]
source_ids: [S25, S23]
-->
### DV01, PV01 and sign conventions

**What this establishes:** Currency-per-bp sensitivity requires an explicit sign and shocked factor.

For a conventional long fixed-rate bond, define positive DV01 magnitude D = D_mod × P_dirty × 0.0001, with P_dirty in currency for the actual position size. Then ΔV ≈ −D × Δy_bp. Some systems instead report signed value change for a +1 bp move, which is approximately −D for this long bond.

Example: USD 10 million full market value and modified duration 7.5 imply about USD 7,500 DV01. A parallel +10 bp yield move implies about USD −75,000 first-order P&L. Convexity and curve shape can change the result.

PV01/BPV can mean a curve-bump sensitivity, yield sensitivity or value of one bp of a swap coupon. These are not universally identical. Record currency, size, curve, bump definition and whether the output is a signed change or positive magnitude.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S25](#source-s25), Basis Point Value; [S23](#source-s23), §§98.42–44; example and sign reconciliation derived here.

<!-- MMR
id: bonds.risk.convexity
asset_classes: [rates]
instrument_families: [government-bonds]
concepts: [convexity, second-order, nonlinear-risk]
source_ids: [S25, S23]
-->
### Bond convexity and nonlinear rate risk

**What this establishes:** Duration is only the first term of a price response.

For price P(y), define D_mod = −P′(y)/P and convexity C = P″(y)/P using decimal yield. A second-order approximation is ΔP/P ≈ −D_mod × Δy + 0.5 × C × (Δy)^2.

For ordinary option-free bonds with positive fixed cash flows and standard positive discount denominators, convexity is positive: the price/yield curve bends upward. This does not mean every bond-like instrument or every portfolio has positive convexity. Embedded options, callable cash flows and short positions can change the result.

Equal DV01 does not ensure equal P&L for large shocks because convexities can differ. Parallel-yield convexity also does not capture all cross-effects from curve reshaping. Repricing specified cash flows under the actual scenario is distinct from extrapolating a local derivative.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S25](#source-s25), price/yield and duration discussion; [S23](#source-s23), §98.35 option-related convexity; second-order formula and positivity follow by differentiating the price identity.

<!-- MMR
id: bonds.curves.spreads
asset_classes: [rates]
instrument_families: [government-bonds, ois]
concepts: [yield-curve, zero-rate, par-rate, spread, swap-spread]
source_ids: [S12, S23, S14]
-->
### Curve points and spread definitions

**What this establishes:** A yield spread is meaningful only when both quantities and their conventions are specified.

A zero/spot curve discounts individual future payments. A par curve gives coupons that price hypothetical coupon instruments at par. A forward curve describes rates between future dates implied by a discount curve. A benchmark bond yield is the YTM of a particular security, not automatically any of these curve rates.

A simple government spread might be y_A − y_B for specified maturities. Define a swap spread here as fixed swap rate minus comparable government-bond yield. Others may reverse the sign. Maturity mismatch, coupon differences, liquidity, credit, collateral and funding can contribute to observed spreads.

Comparing nominal and inflation-linked yields also requires attention to indexation, liquidity and risk premia; their difference is not an exact forecast of realized inflation. This baseline does not supply OAS or structured-credit valuation conventions.

**Scope/currentness:** Definitions are enduring; benchmark securities, interpolation and spread conventions are market-specific.

**Sources:** [S12](#source-s12), curve definitions; [S23](#source-s23), §98.7 rate components; [S14](#source-s14), basis-market discussion.

<!-- MMR
id: bonds.funding.repo
asset_classes: [rates]
instrument_families: [government-bonds, repo, money-market]
concepts: [repo, haircut, funding, specialness]
source_ids: [S24, S26, S11]
-->
### Repo, reverse repo and financing a bond

**What this establishes:** Repo joins a securities transfer with an agreed reverse transfer to provide secured financing.

From the cash borrower’s perspective, repo sells securities and agrees to repurchase them later. The cash lender describes the other side as reverse repo. The repurchase difference reflects the agreed repo interest and conventions. Economic secured financing and legal title-transfer form are distinct descriptions.

A haircut makes cash advanced smaller than the collateral’s agreed value. The residual funding requirement, margin adjustments and rollover can matter even if the bond price changes little. General-collateral financing differs from security-specific borrowing: scarce securities can trade “special” at repo rates below general collateral.

Financing a long bond costs cash; borrowing a security for a short position can involve different availability and costs. Repo does not remove issuer, counterparty, collateral-value or settlement exposure. Overnight funding of a long-maturity bond creates refinancing exposure.

**Scope/currentness:** Foundational structure; haircuts, legal treatment and actual financing terms vary. Handbook evidence is from official indexed extracts.

**Sources:** [S24](#source-s24), Chapter 7 §7.2.2 and Chapter 1 §1.4; [S26](#source-s26), implied-repo/funding discussion; [S11](#source-s11), SOFR market scope.

<!-- MMR
id: bonds.returns.carry-roll
asset_classes: [rates]
instrument_families: [government-bonds, repo]
concepts: [carry, rolldown, funding, horizon]
source_ids: [S26, S21, S12]
-->
### Bond carry, rolldown and funding

**What this establishes:** Coupon income, financing and aging along a curve are distinct return components.

For a stated horizon, coupon/accrual income less financing is one common definition of net carry. Rolldown is the price effect of a bond aging to a shorter remaining maturity under a stated unchanged-curve scenario. Definitions vary; some desks include rolldown or pull-to-par in “carry,” so labels need an explicit decomposition.

On an upward-sloping curve, a shorter remaining maturity may have a lower yield in that scenario; the price effect depends on cash flows and curve shape. This is a scenario, not a promise that the future curve will remain unchanged.

Holding yield constant, holding a constant-maturity curve constant and holding clean price constant are different assumptions. An unchanged coupon is not unchanged carry if funding changes. Do not add coupon cash, accrued-interest growth and a total-return mark in a way that counts the same income twice.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S26](#source-s26), basis/carry financing analysis; [S21](#source-s21), coupon and price mechanics; [S12](#source-s12), maturity-dependent curve definitions; scenario decomposition synthesized here.

<!-- MMR
id: futures.contract.lifecycle
asset_classes: [cross-asset]
instrument_families: [futures]
concepts: [contract, expiry, delivery, cash-settlement]
source_ids: [S33, S34, S29, S16]
-->
### Futures contract and lifecycle

**What this establishes:** Exchange rules define an obligation with specific units and termination mechanics.

A futures contract specifies its underlying or settlement reference, size, quotation, trading calendar and settlement method. Physical delivery and cash settlement are different endpoints. A physically delivered bond future can require securities and invoice cash; a cash-settled rate future terminates through its specified cash calculation.

An offsetting trade in the same contract can close exposure before termination. Last trading day, first notice day and delivery dates need not coincide. A contract month alone is insufficient to identify all deadlines.

Contract multipliers convert quote changes into currency P&L; price limits, tick increments and eligibility rules are product-specific. A futures purchase normally does not require payment of the full underlying notional at inception, but creates margin and eventual settlement obligations.

**Scope/currentness:** Structural baseline; current rulebook and clearing/FCM arrangements control actual terms.

**Sources:** [S33](#source-s33), §§1 and 4; [S34](#source-s34), market operation; [S29](#source-s29), delivery rules; [S16](#source-s16), cash settlement.

<!-- MMR
id: futures.margin.cashflows
asset_classes: [cross-asset]
instrument_families: [futures]
concepts: [initial-margin, maintenance-margin, variation-margin, liquidity]
source_ids: [S34, S36, S33]
-->
### Initial margin, variation settlement and liquidity

**What this establishes:** Collateral requirements and cash P&L are separate from the contract’s full exposure.

Initial margin is a performance-bond requirement. Maintenance requirements and house rules determine when additional funds are required. Variation settlement credits or debits changes in contract settlement value; calls can be intraday as well as daily under applicable arrangements.

Posting recoverable collateral is not itself a trading loss, although financing it can cost money. Paying variation on a losing futures mark is a cash outflow reflecting P&L. Required collateral can also increase without a new position. An economically offsetting cash bond may not provide immediately available cash to meet a futures payment.

Failure to meet requirements can lead to liquidation under the relevant agreement. Initial margin is neither maximum loss nor an option premium. Security-futures margin examples in NFA material do not specify rates- or FX-futures margin levels.

**Scope/currentness:** Enduring distinctions; actual margin levels, eligibility and deadlines are variable and are not specified here.

**Sources:** [S34](#source-s34), margin and daily settlement; [S36](#source-s36), §§1 and 4; [S33](#source-s33), §4.

<!-- MMR
id: futures.positions.open-interest
asset_classes: [cross-asset]
instrument_families: [futures]
concepts: [open-interest, volume, position, netting]
source_ids: [S35]
-->
### Open interest, volume and an individual position

**What this establishes:** Market-wide counts do not reveal an individual trader’s direction.

An individual position is the signed number of contracts held in a specified contract and account/netting scope. Open interest counts outstanding contracts, counting one side of each long/short pair, not both. Volume counts contracts traded during an interval.

An opening buyer matched with an opening seller increases open interest by one contract. Two closing sides reduce it by one. An opening side matched with a closing side leaves it unchanged. Each trade contributes to volume regardless of whether it opens or closes exposure.

High open interest does not mean the market is “net long”: every outstanding future has a long and a short. Public participant-category positions add information but do not make open interest itself a directional signal. Liquidity also depends on executable depth and spreads, not just outstanding contracts.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S35](#source-s35), Open Interest and Volume entries; opening/closing bookkeeping derived here.

<!-- MMR
id: futures.roll.basis
asset_classes: [cross-asset]
instrument_families: [futures]
concepts: [roll, calendar-spread, basis, convergence]
source_ids: [S33, S35, S27]
-->
### Futures expiry rolls and basis risk

**What this establishes:** Rolling changes the contract held and does not mechanically lock a profit from a price gap.

Rolling typically closes one expiry and opens another. The price difference between expiries reflects their different delivery or fixing periods and relevant financing, storage, income or other product economics. A back-adjusted continuous chart is not a directly tradable contract price series.

Define basis before using it: cash minus futures is one convention; Treasury basis additionally uses a conversion factor. Cash and futures exposures can respond differently before expiry. Convergence applies to the specified deliverable or settlement reference under the contract rules, not to an arbitrary proxy security.

Buying a cheaper deferred contract does not instantly earn the inter-contract price difference. Entry and exit trades, subsequent marks and the new contract’s convergence determine P&L. Roll execution can also incur bid/ask costs and change duration, fixing-window or delivery exposure.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S33](#source-s33), §4 expiration/roll mechanics; [S35](#source-s35), Basis; [S27](#source-s27), Treasury-specific basis; contract-switch arithmetic synthesized here.

<!-- MMR
id: treasury-futures.delivery.invoice
asset_classes: [rates]
instrument_families: [treasury-futures]
concepts: [delivery, invoice, conversion-factor, contract-size]
source_ids: [S29, S28]
-->
### Treasury futures delivery and conversion factors

**What this establishes:** The futures quote and the invoice paid for a deliverable security are different amounts.

For conventional CBOT 10-year Treasury-note futures, the current rulebook specifies USD 100,000 face per contract. With F quoted per 100 face, invoice dollars = 1,000 × F × CF + accrued-interest dollars for the delivered face amount. Daily futures price P&L uses USD 1,000 per point without multiplying by CF. The short chooses an eligible issue and delivery timing within the rules.

CF is a conversion factor constructed using a standardized 6% yield and contract-specific rounding. It adjusts invoicing across eligible coupon/maturity combinations; it does not make their market values, durations or financing costs identical.

Verified 2026-10-02: Chapter 19 specifies remaining maturity of at least 6 years 6 months and less than 8 years, with its stated rounding and eligibility conditions. The product’s “10-year” market label does not mean delivery of a newly issued exact 10-year bond. Other Treasury futures have different baskets and units.

**Scope/currentness:** Product-specific facts verified 2026-10-02; Chapter 19 controls over historical guides.

**Sources:** [S29](#source-s29), §§19101–19104; [S28](#source-s28), conversion-factor construction.

<!-- MMR
id: treasury-futures.delivery.ctd
asset_classes: [rates]
instrument_families: [treasury-futures]
concepts: [ctd, delivery-option, quality-option, timing-option]
source_ids: [S26, S29]
-->
### Cheapest-to-deliver and delivery options

**What this establishes:** The economically preferred deliverable can change with prices, yields and financing.

Cheapest-to-deliver (CTD) identifies the eligible bond most economical for a short to acquire, finance and deliver under stated assumptions. Conversion factors do not remove differences in coupon cash flows, duration, repo rates or delivery timing.

Comparing candidate delivery economics requires consistent invoice, accrued interest, coupon dates, financing and delivery dates. Selecting the lowest clean price or lowest unadjusted cash-futures difference is insufficient. Maximum implied repo and minimum net delivery cost align only with consistent assumptions.

The short’s issue and timing choices have option value. A rate move or security-specific financing change can switch CTD and alter futures sensitivity. Delivery timing, notice rules and any trading/delivery time mismatch create residual risks; details are contract-specific. A futures position is not a fixed holding of today’s CTD forever.

**Scope/currentness:** Mechanics endure; current CTD and option value are market-dependent and are not estimated here.

**Sources:** [S26](#source-s26), CTD and delivery-option sections; [S29](#source-s29), §§19103–19104.

<!-- MMR
id: treasury-futures.basis.repo
asset_classes: [rates]
instrument_families: [treasury-futures, government-bonds, repo]
concepts: [gross-basis, net-basis, implied-repo, funding]
source_ids: [S27, S26, S36]
-->
### Gross basis, net basis and implied repo

**What this establishes:** Basis measures and financing comparisons require consistent units and dates.

Using clean cash price P and futures price F per 100 face, define gross basis B = P − CF × F. Define net basis here as gross basis minus carry to a specified delivery date, with carry measuring bond income/accrual net of financing on a consistent basis. Other sign or carry conventions must be translated explicitly.

Implied repo is the financing return inferred from buying the bond and selling futures for delivery, accounting for the purchase invoice, intermediate coupons and delivery invoice. It is not the actual repo rate available to that participant.

An apparent positive financing spread is not automatically realizable profit: funding, haircuts, execution, delivery options, security availability and timing can differ from assumptions. A basis trade can have large gross cash and margin needs while its net parallel DV01 is small.

**Scope/currentness:** Definitions are convention-dependent; funding rates and executable basis are date-specific.

**Sources:** [S27](#source-s27), cash/futures basis; [S26](#source-s26), implied-repo and carry discussion; [S36](#source-s36), liquidity consequences of margin.

<!-- MMR
id: treasury-futures.risk.hedge
asset_classes: [rates]
instrument_families: [treasury-futures, government-bonds]
concepts: [ctd-dv01, hedge-ratio, bpv, duration-matching]
source_ids: [S30]
-->
### Treasury futures DV01 and hedge ratios

**What this establishes:** Futures hedges match rate sensitivity, not simply face amount.

For an unchanged CTD and delivery assumption, futures DV01 is approximately CTD DV01 divided by its conversion factor, with the CTD DV01 scaled to the contract’s deliverable face amount. It is not CTD DV01 multiplied by CF.

If a long bond portfolio has positive DV01 magnitude D_P and a long futures contract has magnitude D_F, a parallel-rate hedge sells approximately D_P / D_F contracts. Hypothetical D_P = USD 12,000/bp, CTD DV01 = USD 72/bp and CF = 0.90 give D_F ≈ USD 80/bp and 150 short contracts.

This neutralizes the chosen first-order parallel sensitivity only. Contract rounding, curve exposure, changing CTD, delivery options, convexity and basis leave residual P&L. Cash DV01 versus forward/delivery-adjusted DV01 must be distinguished in more precise implementations.

**Scope/currentness:** Local approximation; actual DV01 and CTD must be refreshed for the trade date.

**Sources:** [S30](#source-s30), CTD/CF sensitivity relation; numeric example and hedge arithmetic derived here.

<!-- MMR
id: curves.slopes.direction
asset_classes: [rates]
instrument_families: [government-bonds, swaps, rates-futures]
concepts: [steepener, flattener, bull-steepener, bear-flattener]
source_ids: [S31]
-->
### Steepeners, flatteners and bull/bear terminology

**What this establishes:** Slope direction and overall yield direction are separate dimensions.

Define slope s = y_long − y_short. Steepening means Δs > 0; flattening means Δs < 0, including movements through inversion. “Bull” conventionally refers to falling yields/rising conventional bond prices; “bear” to rising yields/falling bond prices.

| Move | Illustrative short/long yield changes | Slope change |
|---|---|---|
| Bull steepening | −20 / −10 bp | +10 bp |
| Bear steepening | +10 / +20 bp | +10 bp |
| Bull flattening | −10 / −20 bp | −10 bp |
| Bear flattening | +20 / +10 bp | −10 bp |

For equal positive DV01 magnitudes D, long the short-maturity bond and short the long-maturity bond gives approximate P&L D × (Δy_long − Δy_short): a steepener. Reverse both legs for a flattener. Mixed-sign yield moves are best described explicitly rather than forced into a bull/bear label.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S31](#source-s31), slope and BPV-weighted spread construction; table and P&L identities derived here.

<!-- MMR
id: curves.butterflies.weights
asset_classes: [rates]
instrument_families: [government-bonds, swaps, rates-futures]
concepts: [butterfly, curvature, weights, dv01-neutral]
source_ids: [S31, S23]
-->
### Butterflies and curvature weights

**What this establishes:** A butterfly definition must state its sign and weights.

For short, middle and long maturities, define one yield butterfly b = 2y_middle − y_short − y_long. This is a convention, not the only butterfly quote. Positive Δb means the belly yield rose relative to equally weighted wings.

With DV01 units +D in the short wing, −2D in the belly and +D in the long wing, approximate P&L is D × Δb_bp. This means long both wings and short the belly in price/duration terms. The reverse trade profits from declining b, before other effects.

Zero summed DV01 removes first-order parallel risk, not every slope exposure. Unequal maturity spacing may require different weights to neutralize a chosen slope factor. Equal notional, equal DV01 and regression-weighted butterflies are different portfolios. “Long the fly” is incomplete without the quote and position conventions.

**Scope/currentness:** Declared convention and derived linear approximation; weighting is not a recommended trading strategy.

**Sources:** [S31](#source-s31), matched-BPV principle; [S23](#source-s23), non-parallel risk limitations; three-leg extension and sign algebra derived here.

<!-- MMR
id: curves.cross-market.comparability
asset_classes: [rates, fx]
instrument_families: [government-bonds, swaps, rates-futures]
concepts: [cross-market, matched-risk, currency-hedge, relative-value]
source_ids: [S07, S23, S26, S31]
-->
### Cross-market rates relative value

**What this establishes:** An observed spread can reflect different instruments and financing structures.

A cross-market comparison identifies currencies, maturities, cash-flow schedules, benchmarks and quote conventions. Equal local-currency notional is not equal DV01. Convert sensitivities into a common reporting currency for a stated FX rate before describing a hedge as risk matched.

Matched parallel DV01 still leaves non-parallel curve risk, currency translation, benchmark basis, sovereign credit, liquidity and convexity differences. Hedging FX adds forward points, basis, collateral and rollover exposure. It does not erase these financing costs.

Apparent relative value can come from coupon/duration mismatch, different policy paths, term premia, repo specialness, deliverability, taxes or timing rather than a mispricing. Curve carry/roll depends on the separate curves and holding horizon. A spread level alone establishes neither an equilibrium nor expected convergence.

**Scope/currentness:** Comparability checklist synthesized from mechanics; no fair-value model or market ranking is asserted.

**Sources:** [S07](#source-s07), cross-currency basis; [S23](#source-s23), rate components and risk measures; [S26](#source-s26), financing/deliverability; [S31](#source-s31), BPV matching.

<!-- MMR
id: pnl.decomposition.cashflows
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [pnl, carry, funding, cashflows, attribution]
source_ids: [S34, S21, S23]
-->
### Economic P&L and cash-flow reconciliation

**What this establishes:** A complete P&L account reconciles remaining value with cash already received or paid.

For a position with no new trades, define V as the value of remaining contractual rights/obligations, excluding separately tracked cash. Economic P&L over the interval is V_end − V_start + net attributable cash received − separately charged costs. Funding belongs either inside the valued financing portfolio or as separate cash flows, never both. Deposits/withdrawals of owner capital are not profit.

For a financed bond: change in dirty value + coupons received − financing interest − costs. Principal repayment belongs in cash as the bond’s remaining value falls. For a settled-to-market future: cash variation plus any unsettled residual value change; do not also count cumulative quote P&L a second time.

Carry, roll, curve movement, spread movement, FX translation and residual terms are attribution choices around this reconciliation. Their split depends on the baseline scenario and order of repricing; total economic P&L is less convention-dependent.

**Scope/currentness:** Accounting identity under declared cash/valuation perimeter; attribution conventions are not unique.

**Sources:** [S34](#source-s34), futures settlement; [S21](#source-s21), bond cash flows; [S23](#source-s23), economic value versus income; reconciliation identity derived here.

<!-- MMR
id: pnl.flat-marks
asset_classes: [cross-asset]
instrument_families: [government-bonds, forwards, futures, options]
concepts: [flat-marks, accrued-interest, carry, theta, funding]
source_ids: [S46, S09, S43, S34]
-->
### Unchanged quotes and non-zero P&L

**What this establishes:** A flat displayed quote is weaker than a flat complete economic valuation.

A bond’s clean price can stay constant while accrued interest grows. A coupon payment transfers value from the security to cash. An unchanged yield can coexist with aging, accrual and pull-to-par. Flat spot FX does not imply flat forward value as maturity and discount factors change. An option can change value as time passes with its underlying unchanged.

Hypothetical financed bond: clean-value change zero, accrued-interest increase USD 1,000, no coupon payment, funding cost USD 600. Economic P&L is USD +400 before other costs. The accrued amount is not added again if the reported mark already includes it.

For a fixed futures position, unchanged entry/end settlement quotes imply zero cumulative price P&L before costs and funding, even if daily variation moved in between. If all complete remaining values and all net attributable cash flows/costs are unchanged or zero, economic P&L is zero. Carry is not a license to invent extra profit.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S46](#source-s46), accrued-interest treatment; [S09](#source-s09), forward/futures financing; [S43](#source-s43), time sensitivity; [S34](#source-s34), daily settlement; example derived here.

<!-- MMR
id: trade.exposure.hedges
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [exposure, hedge-ratio, basis-risk, sensitivity]
source_ids: [S34, S30, S44]
-->
### Exposure, hedge ratio and basis risk

**What this establishes:** A hedge offsets specified risk factors; it need not offset all outcomes.

Let a position’s value change approximately A × Δx for risk factor x, and one unit of a hedge change B × Δx. A signed hedge quantity q = −A/B neutralizes that local factor if B is nonzero. Both sensitivities must use the same factor, units and currency.

For multiple factors, exposure is a vector. One hedge generally cannot remove every component. A currency hedge may leave rate risk; a duration hedge may leave curve/basis risk; a delta hedge leaves gamma and volatility risk. Historical correlation is not a contractual equality.

Hedge effectiveness can change as prices, time, weights or contractual cash flows change. Matching gross notional or labelling two instruments “rates” does not demonstrate an offset. These identities specify what is hedged, not how much risk a trader ought to take.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S34](#source-s34), offsetting-exposure purpose; [S30](#source-s30), DV01 hedge construction; [S44](#source-s44), nonlinear sensitivities; general local hedge algebra derived here.

<!-- MMR
id: trade.execution.costs
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [liquidity, bid-ask, slippage, market-impact, fees]
source_ids: [S04, S37, S35]
-->
### Liquidity, bid/ask and transaction costs

**What this establishes:** An indicative mark and an executable trade can produce different economic results.

Bid/ask spread, commissions, exchange/clearing fees, market impact and execution slippage can separate a model mark from realized proceeds. Financing, collateral remuneration and security-borrow charges are additional holding costs, not necessarily included in an execution spread.

Liquidity is conditional on size, timing, venue, credit and order constraints. Displayed depth can change before an order executes. A limit price constrains execution price but does not guarantee a fill; a market instruction seeks execution against available liquidity, subject to venue protections.

For a hypothetical immediate round trip in an unchanged market, buying at the ask and selling at the bid loses the spread plus fees. Multiplying by the correct size and quote multiplier gives the currency cost. A reported mid-price gain can therefore coexist with a smaller executable gain or a loss.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S04](#source-s04), Execution; [S37](#source-s37), §2 order execution; [S35](#source-s35), market vocabulary; round-trip cost identity derived here.

<!-- MMR
id: trade.risk.leverage
asset_classes: [cross-asset]
instrument_families: [futures, repo, swaps, options]
concepts: [leverage, margin, funding-liquidity, loss]
source_ids: [S36, S34]
-->
### Leverage and collateral liquidity

**What this establishes:** A small initial cash commitment does not make an exposure economically small.

Leverage compares an exposure measure with capital committed or equity supporting it. The denominator and numerator must be stated: gross notional/equity, market value/equity and DV01/equity describe different things. Netting directional exposures does not necessarily net margin or settlement cash across accounts.

With a fixed contract position, a lower collateral requirement does not reduce currency P&L for a given market move; it increases that P&L relative to posted collateral. Losses can exceed initial margin. A variation call or haircut increase can require cash before an offsetting asset is sold or a thesis horizon ends.

Risk limits, margin requirements and solvency are distinct constraints. Margin-based liquidation follows the applicable clearing/broker agreement and resources available, not the economic narrative attached to a position.

**Scope/currentness:** Mechanical baseline; no current margin amount, legal liquidation entitlement or leverage target is prescribed.

**Sources:** [S36](#source-s36), §4 Margin and Leverage (general mechanism only); [S34](#source-s34), performance-bond mechanics; ratio interpretations derived here.

<!-- MMR
id: trade.orders.stops
asset_classes: [cross-asset]
instrument_families: [futures, cash-securities]
concepts: [stop-market, stop-limit, liquidation, gap-risk]
source_ids: [S37, S36]
-->
### Stops, execution and forced liquidation

**What this establishes:** A stop instruction is different from a contractual margin liquidation process.

A stop is triggered under a specified price/event rule. A stop-market instruction then seeks execution under venue rules; the trigger is not a guaranteed fill price. A stop-limit instruction imposes a price limit after triggering and may remain unfilled. Gaps, insufficient depth and venue protection bands can affect the result.

Forced liquidation is closure initiated under clearing/broker or other contractual rules, for example when required collateral is not supplied. It need not occur at a trader’s chosen stop or wait for a thesis to be reassessed.

A stop level therefore does not mechanically cap loss at the trigger-distance calculation. Exact supported order types, trigger references, protection ranges and liquidation rights are venue/account-specific. No stop placement or trading style is recommended here.

**Scope/currentness:** Order distinction is enduring; historical CFTC paper protection-point examples are not current specifications.

**Sources:** [S37](#source-s37), §2 Background, printed pp. 2–3; [S36](#source-s36), §4 liquidation discussion.

<!-- MMR
id: trade.time.horizon
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [event-window, thesis-horizon, maturity, expiry, path-risk]
source_ids: [S23, S16, S17, S38]
-->
### Thesis horizon, event window and instrument maturity

**What this establishes:** Contract exposure through an event is not identical to eventual valuation convergence.

A valuation horizon describes when a valuation premise might be assessed. An event window specifies a short observation or holding interval around an event. Instrument maturity fixes contractual timing. These dates can differ without contradiction.

A two-day holding in a ten-year bond realizes changes in its exit price plus intervening cash flows/costs, not ten years of eventual cash flows at face value. An option expiring before a proposed convergence date does not provide the same contractual coverage as one surviving it. A STIR future averages its defined fixing window, so one meeting may affect only part of that window.

Interim mark-to-market and collateral payments can occur before the thesis horizon. These are baseline timing distinctions. Whether a catalyst will cause repricing, or which horizon/expression is attractive, remains a contextual judgment outside the reference.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S23](#source-s23), §98.19 time horizons; [S16](#source-s16)/[S17](#source-s17), fixing windows; [S38](#source-s38), option expiry; holding-period examples derived here.

<!-- MMR
id: trade.positions.close-reverse
asset_classes: [cross-asset]
instrument_families: [all]
concepts: [close, reduce, reverse, exposure, thesis-invalidation]
source_ids: [S35]
-->
### Closing, reducing and reversing a position

**What this establishes:** Removing an exposure and taking its opposite are different transactions.

Using signed units q, closing a +q position to zero requires selling q. Reversing from +q to −q requires selling 2q: q to close and another q to establish the opposite exposure. Reducing to a smaller positive position is neither closure nor reversal. Lot accounting and netting rules govern how the trades are recorded.

The reversed position has opposite first-order exposure for a linear contract, plus new execution, funding and margin consequences. For nonlinear portfolios, “opposite view” need not mean an exact negative payoff unless all relevant positions are reversed.

No contract or P&L identity makes invalidation of one explanatory premise establish the expected return of an opposite position. That last distinction is a limit of what mechanics can conclude, not a rule forbidding reversal. Assessing a new thesis belongs to reasoning and experiential review.

**Scope/currentness:** Exposure identity plus explicitly stated reasoning boundary; no source is attributed a thesis-management doctrine.

**Sources:** [S35](#source-s35), Long/Short and offsetting-position vocabulary; signed-position arithmetic derived here.

<!-- MMR
id: options.payoff.rights
asset_classes: [cross-asset]
instrument_families: [vanilla-options, options-on-futures]
concepts: [call, put, strike, exercise, expiry]
source_ids: [S38, S33]
-->
### Calls, puts, exercise and obligations

**What this establishes:** An option buyer’s right and a futures obligation have different payoff structures.

A vanilla call gives the holder a right to buy the specified underlying at strike K under the exercise terms; a put gives a right to sell. The writer has the corresponding obligation if exercised/assigned. Cash-settled options pay the specified equivalent instead of delivering the underlying.

At expiry, per-unit call payoff is max(U − K, 0); put payoff is max(K − U, 0), using the contract’s settlement reference U. Long-option net P&L also subtracts premium and costs. A payoff diagram omitting premium is not a profit diagram.

European exercise occurs at expiry; American exercise is possible within its specified exercise period. Futures options can exercise into futures positions, creating subsequent margin/exposure. Multiplier, settlement style, exercise cutoff and automatic-exercise rules must be checked for the actual product.

**Scope/currentness:** Vanilla baseline; exchange-specific option exercise/delivery specifications are outside this compact module.

**Sources:** [S38](#source-s38), rights and exercise; [S33](#source-s33), futures/options distinction; payoff algebra derived here.

<!-- MMR
id: options.value.premium
asset_classes: [cross-asset]
instrument_families: [vanilla-options]
concepts: [premium, intrinsic-value, time-value, discounting]
source_ids: [S39, S38]
-->
### Premium, intrinsic value and time value

**What this establishes:** Option price depends on more than the underlying’s current distance from strike.

Intrinsic payoff evaluated at the current underlying is max(U − K,0) for a call and max(K − U,0) for a put. Time/extrinsic value is commonly quoted as premium minus that amount. The comparison requires the correct underlying and premium units.

An immediately exercisable option has an exercise-based value floor under suitable frictionless assumptions. A European option cannot necessarily be exercised now; its price need not exceed that unadjusted immediate-exercise amount in all rate/dividend configurations. Do not make nonnegative “time value” a universal rule across exercise styles and quotation conventions.

Underlying price, strike, time, volatility, rates, distributions and contract terms affect valuation. Premium paid up front differs from futures-style premium/margin arrangements. The maximum loss of a standalone fully paid long option before exercise is its premium plus costs; exercising it can create a new exposure.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S39](#source-s39), pricing inputs and intrinsic/time value; [S38](#source-s38), exercise rights; exercise-style qualification follows from the timing of the stated rights.

<!-- MMR
id: options.risk.delta-gamma
asset_classes: [cross-asset]
instrument_families: [vanilla-options, options-on-futures]
concepts: [delta, gamma, convexity, hedge]
source_ids: [S40, S41, S44]
-->
### Delta, gamma and local convexity

**What this establishes:** Delta is a local slope and gamma measures how that slope changes.

For option value V and underlying price U, delta = ∂V/∂U and gamma = ∂²V/∂U². Local underlying-driven change is approximately delta × ΔU + 0.5 × gamma × (ΔU)^2. Contract multiplier and quantity convert per-unit sensitivities to currency exposure.

Standard long vanilla calls have positive delta; long vanilla puts have negative delta. Standard long vanilla calls and puts have positive gamma in conventional models; short positions reverse these signs. No universal sign claim is made for arbitrary exotic portfolios.

Delta changes with price, time and volatility. It is not universally an exercise probability; probability interpretations depend on model and measure. Delta neutral today does not mean zero P&L after a finite move. Gamma is payoff curvature, not guaranteed profit after premium, time decay, hedging costs and volatility changes.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S40](#source-s40), delta; [S41](#source-s41), gamma; [S44](#source-s44), approximation limits; Taylor expansion derived here.

<!-- MMR
id: options.risk.vega-theta
asset_classes: [cross-asset]
instrument_families: [vanilla-options]
concepts: [vega, theta, volatility-point, time-decay]
source_ids: [S42, S43, S44]
-->
### Vega, theta and sensitivity units

**What this establishes:** Volatility and elapsed time can change option value even with the underlying unchanged.

Vega measures sensitivity to a change in implied volatility, commonly reported per one volatility percentage point. Moving volatility from 20% to 21% is one such point, not a 1% relative increase. Standard long vanilla options generally have positive vega under conventional models; portfolio and exotic signs can differ.

Theta usually denotes change in option value as calendar time passes with other inputs fixed, but systems can use time-to-expiry or different day units, reversing or rescaling reported signs. Long vanilla options often have negative calendar-time theta; this is not universal for every rate, moneyness and exercise configuration.

For consistent units, local P&L can include delta × ΔU + 0.5 gamma × (ΔU)^2 + vega × Δσ + theta × Δt. Cross-terms, changing Greeks and large moves limit the approximation. Theta is a scenario sensitivity, not a separate cash coupon.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S42](#source-s42), vega; [S43](#source-s43), theta; [S44](#source-s44), model sensitivity limits; multivariate approximation derived here.

<!-- MMR
id: options.volatility.implied-realized
asset_classes: [cross-asset]
instrument_families: [vanilla-options]
concepts: [implied-volatility, realized-volatility, smile, model]
source_ids: [S44, S39]
-->
### Implied and realized volatility

**What this establishes:** Implied volatility is a model-inverted price input; realized volatility is a measured return statistic.

Implied volatility is the volatility parameter making a specified pricing model reproduce an observed option price given its other inputs. Different strikes and maturities can imply different values. A single volatility number does not describe an entire option surface.

Realized volatility summarizes observed returns over a defined sampling interval and window, with an annualization convention. Sampling frequency, treatment of jumps and market hours can change the estimate. Historical realized volatility and forward-looking implied volatility refer to different objects.

The difference between them is not mechanically guaranteed profit. An option position’s result depends on premium, path, strike, changing sensitivities, hedging, funding and costs. A delta-hedged option is not a pure variance contract in every circumstance. This compact baseline does not cover exotic payoffs, volatility-surface construction or model calibration.

**Scope/currentness:** Enduring mechanics; contractual conventions must be checked for the instrument.

**Sources:** [S44](#source-s44), historical/implied volatility and Greeks; [S39](#source-s39), model inputs; limitations synthesized from the stated payoff and sensitivities.

<!-- MMR-END -->

## Source register

All sources below were accessed or checked on **2026-10-02 (UTC)**. Section citations name the specific supporting topic or rule. Dates describe publication/version where known; undated pages are not assigned invented publication dates. S24 has limited official-extract access. Requested but unreadable sources are documented in the audit and are not counted as mechanics evidence.

<a id="source-s01"></a>

### S01 — Federal Reserve Bank of New York

- **Document:** [Towards Increasing Complexity: The Evolution of the FX Market](https://libertystreeteconomics.newyorkfed.org/2024/01/towards-increasing-complexity-the-evolution-of-the-fx-market/)
- **Edition/date:** 2024-01-11. Accessed 2026-10-02.
- **Locators:** Market evolution and settlement discussion.
- **Use:** Spot value dates and modernization of dealer-market descriptions.
- **Qualification:** Institutional research, not a rulebook; the article’s prospective discussion of the 2024 securities T+1 transition is historical.

<a id="source-s02"></a>

### S02 — BIS

- **Document:** [OTC foreign exchange turnover in April 2025](https://www.bis.org/publications/202509-commentary-otc-derivatives)
- **Edition/date:** 2025-09-30. Accessed 2026-10-02.
- **Locators:** 2025 Triennial Survey; instruments, counterparties and reporting basis.
- **Use:** Current survey framework and distinctions between turnover, outstanding notional and risk.
- **Qualification:** April 2025 snapshot; no current positioning inference.

<a id="source-s03"></a>

### S03 — BIS

- **Document:** [The FX trade execution landscape through the prism of the 2025 BIS Triennial Survey](https://www.bis.org/publications/qr-202512/fx-trade-execution-landscape-through-prism-2025-bis-triennial-survey)
- **Edition/date:** 2025-12. Accessed 2026-10-02.
- **Locators:** Execution methods, internalisation and counterparties.
- **Use:** Modern electronic, dealer, client and non-bank market structure.
- **Qualification:** Survey-period structure, not a timeless market-share claim.

<a id="source-s04"></a>

### S04 — Global Foreign Exchange Committee

- **Document:** [FX Global Code](https://www.globalfxc.org/uploads/fx_global.pdf)
- **Edition/date:** December 2024 edition. Accessed 2026-10-02.
- **Locators:** Foreword; Execution; Information Sharing; Principle 35; Confirmation and Settlement.
- **Use:** Role disclosure, information handling and settlement conventions.
- **Qualification:** Voluntary conduct guidance; not trading alpha or a substitute for law. Copyright/reuse permission for bulk reproduction not established.

<a id="source-s05"></a>

### S05 — BIS

- **Document:** [Uncovering FX settlement risk: new measures from the 2025 BIS Triennial Survey](https://www.bis.org/publications/qr-202606/uncovering-fx-settlement-risk-new-measures-2025-bis-triennial-survey)
- **Edition/date:** 2026-06. Accessed 2026-10-02.
- **Locators:** Settlement-risk measures and mitigation methods.
- **Use:** Principal risk, payment-versus-payment and netting.
- **Qualification:** Survey measures refer to April 2025; no unsupported claim that all FX uses PvP.

<a id="source-s06"></a>

### S06 — CME Group

- **Document:** [Understanding FX Quote Conventions](https://www.cmegroup.com/education/courses/introduction-to-fx/understanding-fx-quote-conventions)
- **Edition/date:** Undated live educational page. Accessed 2026-10-02.
- **Locators:** Base/terms and futures quotation examples.
- **Use:** Quote orientation and appreciation arithmetic.
- **Qualification:** Pair and venue conventions vary.

<a id="source-s07"></a>

### S07 — BIS

- **Document:** [Covered interest parity lost: understanding the cross-currency basis](https://www.bis.org/publ/qtrpdf/r_qt1609e.pdf)
- **Edition/date:** 2016-09. Accessed 2026-10-02.
- **Locators:** Quarterly Review, pp. 45–64; CIP relationship and deviations.
- **Use:** Covered replication identity and reasons observed basis need not be zero.
- **Qualification:** Historical LIBOR examples are not current benchmark specifications.

<a id="source-s08"></a>

### S08 — CME Group

- **Document:** [Covered Interest Parity, Implied Forward Foreign Exchange Swaps, Cross-Currency Basis and CME €STR Futures](https://www.cmegroup.com/articles/whitepapers/covered-interest-parity-implied-forward-foreign-exchange-swaps-cross-currency-basis-and-cme-estr-futures.html)
- **Edition/date:** Undated live white paper; examples include 2024. Accessed 2026-10-02.
- **Locators:** CIP, swap points and forward-forward examples.
- **Use:** Forward points and two-leg FX funding relationships.
- **Qualification:** Product promotion and trading suggestions excluded.

<a id="source-s09"></a>

### S09 — CME Group

- **Document:** [Reconciling FX Spot Futures Price](https://www.cmegroup.com/education/whitepapers/reconciling-fx-spot-futures-prices)
- **Edition/date:** Undated live white paper; examples from 2014. Accessed 2026-10-02.
- **Locators:** Quote Convention; Cost of Carry.
- **Use:** Carry interpretation and quote-orientation differences.
- **Qualification:** Dated numerical tables and simplified additive carry shorthand are not adopted as exact formulas.

<a id="source-s10"></a>

### S10 — BIS

- **Document:** [Non-deliverable forwards: impact of currency internationalisation and derivatives reform](https://www.bis.org/publications/qr-201612/non-deliverable-forwards-impact-currency-internationalisation-and-derivatives-reform)
- **Edition/date:** 2016-12. Accessed 2026-10-02.
- **Locators:** NDF definition and market segmentation.
- **Use:** Cash settlement and onshore/offshore distinction.
- **Qualification:** Market sizes and regulatory descriptions are historical.

<a id="source-s11"></a>

### S11 — Federal Reserve Bank of New York

- **Document:** [Additional Information about Reference Rates](https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates)
- **Edition/date:** Live methodology; update shown 2026-04-06. Accessed 2026-10-02.
- **Locators:** EFFR and SOFR calculation and publication sections.
- **Use:** Unsecured versus secured overnight benchmarks.
- **Qualification:** Methodology and publication calendars require current verification.

<a id="source-s12"></a>

### S12 — Bank of England

- **Document:** [Yield curves: terminology and concepts](https://www.bankofengland.co.uk/statistics/yield-curves/terminology-and-concepts)
- **Edition/date:** Undated live methodology page. Accessed 2026-10-02.
- **Locators:** Types of instruments; spot, forward and par curves.
- **Use:** OIS cash flows and curve definitions.
- **Qualification:** Older LIBOR-related descriptions are not adopted as current practice.

<a id="source-s13"></a>

### S13 — Bank of England

- **Document:** [Overnight index swap market-based measures of monetary policy expectations](https://www.bankofengland.co.uk/-/media/boe/files/working-paper/2018/overnight-index-swap-market-based.pdf)
- **Edition/date:** 2018-02-09; Staff Working Paper 709, Simon P. Lloyd. Accessed 2026-10-02.
- **Locators:** §1, printed p. 2 (risk premia); §2 (instrument cash flows and expectations hypothesis).
- **Use:** Limits of interpreting traded rates as pure policy forecasts.
- **Qualification:** Author research, not Bank policy; empirical small-premium findings are sample/horizon-specific, not a universal zero-premium identity.

<a id="source-s14"></a>

### S14 — BIS

- **Document:** [Goodbye Libor, hello basis traders: unpacking the surge in global interest rate derivatives turnover](https://www.bis.org/publications/qr-202512/goodbye-libor-hello-basis-traders-unpacking-surge-global-interest-rate-derivatives-turnover)
- **Edition/date:** 2025-12. Accessed 2026-10-02.
- **Locators:** Benchmark transition and OIS discussion.
- **Use:** Current coexistence of overnight and term benchmarks across currencies.
- **Qualification:** 2025 survey context; does not define individual exchange contracts.

<a id="source-s15"></a>

### S15 — CME Group

- **Document:** [Understanding SOFR Futures](https://www.cmegroup.com/education/articles-and-reports/understanding-sofr-futures)
- **Edition/date:** Live guide, including 2026 contract examples. Accessed 2026-10-02.
- **Locators:** Contract naming, reference periods and settlement construction.
- **Use:** SOFR contract orientation and reference-quarter interpretation.
- **Qualification:** Rulebook S16/S17 takes precedence over guide and dated examples.

<a id="source-s16"></a>

### S16 — CME

- **Document:** [Rulebook Chapter 460: Three-Month SOFR Futures](https://www.cmegroup.com/content/dam/cmegroup/rulebook/CME/IV/400/460.pdf)
- **Edition/date:** Live rulebook; verified 2026-10-02. Accessed 2026-10-02.
- **Locators:** 46001; 46002.B–C; 46003.A.1–2.
- **Use:** Authoritative SR3 multiplier, reference quarter and final settlement.
- **Qualification:** Mutable contract specification; no permanent tick, calendar or margin guarantee.

<a id="source-s17"></a>

### S17 — CME

- **Document:** [Rulebook Chapter 461: One-Month SOFR Futures](https://www.cmegroup.com/content/dam/cmegroup/rulebook/CME/IV/400/461.pdf)
- **Edition/date:** Live rulebook; verified 2026-10-02. Accessed 2026-10-02.
- **Locators:** 46101; 46102.B–C; 46103.
- **Use:** Authoritative SR1 multiplier and arithmetic averaging.
- **Qualification:** Mutable contract specification.

<a id="source-s18"></a>

### S18 — CME Group

- **Document:** [Three-Month SOFR Futures Rates and Future SOFR Levels](https://www.cmegroup.com/education/articles-and-reports/three-month-sofr-futures-rates-and-future-sofr-levels)
- **Edition/date:** 2018. Accessed 2026-10-02.
- **Locators:** In general; equations separating known fixings from future days.
- **Use:** Realized fixing versus remaining implied path.
- **Qualification:** 2018 prices are examples only; current rulebook controls.

<a id="source-s19"></a>

### S19 — CME Group

- **Document:** [A Practitioner’s Guide to Three-Month SOFR Futures Contract Notional](https://www.cmegroup.com/articles/whitepapers/a-practitioners-guide-to-three-month-sofr-futures-contract-notional.html)
- **Edition/date:** Undated live white paper. Accessed 2026-10-02.
- **Locators:** Contract BPV and period-dependent equivalent notional.
- **Use:** Why fixed BPV does not mean a literal fixed-size deposit.
- **Qualification:** Equivalent notional is a risk translation, not exchanged principal.

<a id="source-s20"></a>

### S20 — CME Group

- **Document:** [Understanding SOFR Strips](https://www.cmegroup.com/education/courses/introduction-to-sofr/understanding-sofr-strips)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Strip construction and hedge examples.
- **Use:** Contracts across adjacent fixing windows.
- **Qualification:** Examples are not trading recommendations.

<a id="source-s21"></a>

### S21 — US Treasury / TreasuryDirect

- **Document:** [Understanding Pricing and Interest Rates](https://www.treasurydirect.gov/marketable-securities/understanding-pricing/)
- **Edition/date:** Undated live explanatory page. Accessed 2026-10-02.
- **Locators:** Bills; notes and bonds; price and yield.
- **Use:** Coupon, discount and US Treasury cash-flow mechanics.
- **Qualification:** US conventions do not apply automatically to other sovereigns.

<a id="source-s22"></a>

### S22 — FINRA

- **Document:** [Duration: What an Interest Rate Hike Could Do to Your Bond Portfolio](https://syndication.finra.org/content/duration-what-interest-rate-hike-could-do-your-bond-portfolio)
- **Edition/date:** Archived investor education; no edition date relied on. Accessed 2026-10-02.
- **Locators:** Macaulay, modified and effective duration; limitations.
- **Use:** Independent duration explanation and local approximation.
- **Qualification:** Interest-rate-hike framing is not adopted as a market view.

<a id="source-s23"></a>

### S23 — Basel Committee on Banking Supervision / BIS

- **Document:** [Basel Framework SRP98: Application guidance on interest rate risk in the banking book](https://www.bis.org/committees/bcbs/basel-framework/standard/srp/98/inforce/2019-12-15/published/2019-12-15)
- **Edition/date:** Version effective and updated 2019-12-15. Accessed 2026-10-02.
- **Locators:** 98.3–6; 98.18–19; 98.42–44 and footnote 9.
- **Use:** Economic value versus accounting income; time horizons and PV01 limitations.
- **Qualification:** Banking-book regulatory context; no transfer of capital rules into trading policy.

<a id="source-s24"></a>

### S24 — World Bank and IMF

- **Document:** [Developing Government Bond Markets: A Handbook](https://www.elibrary.imf.org/display/book/9780821349557/ch01.xml)
- **Edition/date:** 2001; World Bank first printing July; IMF catalogue September. Accessed 2026-10-02.
- **Locators:** Chapter 1, §1.4 (money markets); companion Chapter 7, §7.2.2 (repo).
- **Use:** Foundational money-market and government-bond funding structure.
- **Qualification:** Only official indexed chapter extracts readable in this session; direct book/PDF access restricted. All rights reserved. No current institutional statistics imported.

<a id="source-s25"></a>

### S25 — CME Group

- **Document:** [Understanding Treasury Futures](https://www.cmegroup.com/content/dam/cmegroup/education/files/understanding-treasury-futures.pdf)
- **Edition/date:** Official PDF copyright 2024; includes older examples. Accessed 2026-10-02.
- **Locators:** Price/yield discussion; Basis Point Value and Duration; risk-management chapters.
- **Use:** Treasury price sensitivity and delivery/futures foundations.
- **Qualification:** Historical deliverable baskets and numerical examples must not override current rules.

<a id="source-s26"></a>

### S26 — CME Group

- **Document:** [Treasury Futures Delivery Options, Basis Spreads, and Delivery Tails](https://www.cmegroup.com/education/files/treasury-futures-basis-spreads.pdf)
- **Edition/date:** Undated official educational PDF. Accessed 2026-10-02.
- **Locators:** CTD, implied repo, basis/carry and delivery-option sections.
- **Use:** Delivery optionality, implied financing and residual basis risk.
- **Qualification:** Historical examples only; document does not establish today’s CTD.

<a id="source-s27"></a>

### S27 — CME Group

- **Document:** [The Basics of Treasuries Basis](https://www.cmegroup.com/education/courses/introduction-to-treasuries/the-basics-of-treasuries-basis)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Cash price, conversion-adjusted futures price and carry.
- **Use:** Gross versus net basis.
- **Qualification:** Basis sign must be stated; convention is not universal.

<a id="source-s28"></a>

### S28 — CME Group

- **Document:** [Calculating US Treasury Futures Conversion Factors](https://www.cmegroup.com/articles/2024/calculating-us-treasury-futures-conversion-factors.html)
- **Edition/date:** 2024. Accessed 2026-10-02.
- **Locators:** 6% standard yield and conversion-factor calculation.
- **Use:** Purpose and limitations of conversion factors.
- **Qualification:** Contract rounding and eligibility are rule-specific.

<a id="source-s29"></a>

### S29 — CBOT / CME Group

- **Document:** [Rulebook Chapter 19: Treasury Note Futures (6½ to 8 Year)](https://www.cmegroup.com/content/dam/cmegroup/rulebook/CBOT/II/19.pdf)
- **Edition/date:** Live rulebook; verified 2026-10-02. Accessed 2026-10-02.
- **Locators:** 19101.A–B; 19102.B–C; 19103; 19104.
- **Use:** Current conventional 10-year Treasury-note futures delivery and invoice rules.
- **Qualification:** Current remaining-maturity basket differs from older educational descriptions.

<a id="source-s30"></a>

### S30 — CME Group

- **Document:** [Calibrating Treasury Link: DV01-Weighted Spreads](https://www.cmegroup.com/articles/2026/calibrating-treasury-link-dv01-weighted-spreads.html)
- **Edition/date:** 2026. Accessed 2026-10-02.
- **Locators:** Futures DV01, CTD and conversion-factor relationship.
- **Use:** CTD-adjusted hedge ratios.
- **Qualification:** Product framing and promotional conclusions excluded.

<a id="source-s31"></a>

### S31 — CME Group

- **Document:** [Trading the Treasury Yield Curve](https://www.cmegroup.com/education/whitepapers/trading-the-treasury-yield-curve)
- **Edition/date:** Undated live white paper; examples include 2014. Accessed 2026-10-02.
- **Locators:** Slope definitions and BPV-weighted spreads.
- **Use:** Curve direction and matched-risk construction.
- **Qualification:** Historical ratios, macro views and inconsistent rounded/example labels not adopted.

<a id="source-s32"></a>

### S32 — CME Group

- **Document:** [Understanding Yield Futures](https://www.cmegroup.com/articles/2024/understanding-yield-futures.html)
- **Edition/date:** 2024. Accessed 2026-10-02.
- **Locators:** Yield quotation and long/short exposure.
- **Use:** Counterexample to treating every rates future as price-quoted.
- **Qualification:** Product-specific quotation; not conventional Treasury futures.

<a id="source-s33"></a>

### S33 — CME Group

- **Document:** [A Trader’s Guide to Futures](https://www.cmegroup.com/content/dam/cmegroup/education/files/a-traders-guide-to-futures.pdf)
- **Edition/date:** Undated official 34-page archived guide. Accessed 2026-10-02.
- **Locators:** §1 What Are Futures?; §4 How Does a Trade Work?.
- **Use:** Standardisation, contract lifecycle and trade cash flows.
- **Qualification:** Trading advice, promotional claims and old market structure excluded.

<a id="source-s34"></a>

### S34 — CFTC

- **Document:** [The Economic Purpose of Futures Markets and How They Work](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/economicpurpose.html)
- **Edition/date:** Undated live educational page. Accessed 2026-10-02.
- **Locators:** Margin, marking to market and hedging discussion.
- **Use:** Independent futures settlement and offsetting-exposure explanation.
- **Qualification:** General education, not an individual contract specification.

<a id="source-s35"></a>

### S35 — CFTC

- **Document:** [Futures Glossary](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/CFTCGlossary/index.htm)
- **Edition/date:** Live glossary. Accessed 2026-10-02.
- **Locators:** Entries: Basis; Hedge; Long; Short; Open Interest; Volume; Leverage.
- **Use:** Common futures vocabulary and position accounting.
- **Qualification:** Definitions require product-specific units.

<a id="source-s36"></a>

### S36 — NFA

- **Document:** [Risk Disclosure Statement for Security Futures Contracts](https://www.nfa.futures.org/investors/investor-resources/files/security-futures-disclosure.pdf)
- **Edition/date:** Undated publisher-hosted version accessed 2026-10-02. Accessed 2026-10-02.
- **Locators:** §1 risk summary; §4 Margin and Leverage, pp. 14–16; §5 Settlement.
- **Use:** Independent explanation of performance bonds, leverage and forced liquidation.
- **Qualification:** Security-futures scope. Its margin percentages and expiry examples are NOT imported into rates/FX futures. Requested Opportunity and Risk guide was not recovered.

<a id="source-s37"></a>

### S37 — CFTC, Office of the Chief Economist

- **Document:** [Stop Orders in Select Futures Markets](https://www.cftc.gov/sites/default/files/Stoploss_final_ada.pdf)
- **Edition/date:** 2017-08-29; Staff Paper 2017-009. Accessed 2026-10-02.
- **Locators:** §2 Background, printed pp. 2–3.
- **Use:** Trigger versus execution price; stop-market versus stop-limit.
- **Qualification:** Authors’ research, not Commission policy; historical protection-point levels excluded.

<a id="source-s38"></a>

### S38 — OCC / Options Industry Council

- **Document:** [What Is an Option?](https://www.optionseducation.org/optionsoverview/what-is-an-option)
- **Edition/date:** Undated live education. Accessed 2026-10-02.
- **Locators:** Call/put rights, exercise and obligations.
- **Use:** Vanilla option payoff and exercise baseline.
- **Qualification:** Equity-option examples do not specify futures-option delivery.

<a id="source-s39"></a>

### S39 — OCC / Options Industry Council

- **Document:** [Options Pricing](https://prd-web.optionseducation.org/optionsoverview/options-pricing)
- **Edition/date:** Undated official education. Accessed 2026-10-02.
- **Locators:** Intrinsic value, time value and pricing inputs.
- **Use:** Premium decomposition and model inputs.
- **Qualification:** Public readability is not a licence to reproduce teaching material.

<a id="source-s40"></a>

### S40 — CME Group

- **Document:** [Options Delta: The Greeks](https://www.cmegroup.com/education/courses/option-greeks/options-delta-the-greeks)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Delta definition and long/short signs.
- **Use:** Local underlying-price sensitivity.
- **Qualification:** Probability shorthand and universal moneyness thresholds excluded.

<a id="source-s41"></a>

### S41 — CME Group

- **Document:** [Options Gamma: The Greeks](https://www.cmegroup.com/education/courses/option-greeks/options-gamma-the-greeks)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Gamma definition.
- **Use:** Delta changes and vanilla convexity.
- **Qualification:** No extension to arbitrary exotic payoffs.

<a id="source-s42"></a>

### S42 — CME Group

- **Document:** [Options Vega: The Greeks](https://www.cmegroup.com/education/courses/option-greeks/options-vega-the-greeks)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Vega definition and volatility-point units.
- **Use:** Implied-volatility sensitivity.
- **Qualification:** Greek depends on model, maturity and underlying.

<a id="source-s43"></a>

### S43 — CME Group

- **Document:** [Theta](https://www.cmegroup.com/education/courses/option-greeks/theta.hideSubnav.educationIframe.html?hideAddThisExt=y&hideFooter=y&hideHeader=y&hideRightRail=y)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Time sensitivity.
- **Use:** Theta conventions and changing time value.
- **Qualification:** No universal daily decay or weekend rule inferred.

<a id="source-s44"></a>

### S44 — OCC / Options Industry Council

- **Document:** [Volatility & the Greeks](https://www.optionseducation.org/advancedconcepts/volatility-the-greeks)
- **Edition/date:** Undated live education. Accessed 2026-10-02.
- **Locators:** Historical/implied volatility and model sensitivities.
- **Use:** Volatility definition and limits of Greek approximations.
- **Qualification:** Model outputs are not guaranteed realized returns.

<a id="source-s45"></a>

### S45 — CME Group

- **Document:** [Understanding Convexity Bias](https://www.cmegroup.com/education/courses/understanding-stir-futures/understanding-convexity-bias)
- **Edition/date:** Undated live course. Accessed 2026-10-02.
- **Locators:** Payout differences between SOFR futures and single-period swaps.
- **Use:** Why futures and swap/forward exposures cannot be equated without adjustment.
- **Qualification:** Linear quoted-rate payout does not imply linearity in every underlying curve input. No universal adjustment size or sign is imported from examples.

<a id="source-s46"></a>

### S46 — FINRA

- **Document:** [Bonds](https://www.finra.org/investors/investing/investment-products/bonds)
- **Edition/date:** Undated live investor-education page. Accessed 2026-10-02.
- **Locators:** Selling Before the Maturity Date; Bond Pricing; Current Yield and Basis Points glossary entries.
- **Use:** Independent accrued-interest, exit-price, quote-unit and current-yield checks.
- **Qualification:** Older product lists and simplified monetary-policy descriptions are not used as current specifications.

For S24’s repo passage, the official companion location is [Chapter 7, §7.2.2](https://www.elibrary.imf.org/display/book/9780821349557/ch07.xml). Source access, reuse limitations and QA are recorded in [the supporting source audit](research/MARKET_MECHANICS_REFERENCE_SOURCE_AUDIT.md).
