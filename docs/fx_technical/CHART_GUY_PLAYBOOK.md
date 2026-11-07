# Chart Guy Playbook — Close-Only G10 FX Technical Analysis

This playbook is written for a spot G10 foreign-exchange trader whose price evidence is **daily closes only**: the ECB euro reference cross rates and equivalent official fixing series. You do not have intraday highs, lows, opens, or volume. You do not synthesize candles from imagination. What follows is how to read structure, momentum, and volatility honestly under that constraint, express ideas on **5-session** and **20-session** horizons, and use **1-session** and **10-session** context without confusing them for holding periods.

The posture throughout is conservative: separate **fact**, **inference**, and **unknown**; when indicators disagree, default to **no-trade** or a smaller expression; never treat a descriptive cross or an extreme oscillator reading as an order to reverse.

---

## What a close-only series can and cannot support

A single daily close tells you where the cross **finished** the session in fixing terms. It is a settlement mark, not a map of how price traded inside the day. From a sequence of closes you can compute returns, moving averages, Wilder RSI, MACD, realized volatility, and close-based range levels. You can infer swing structure **only after** later closes confirm or reject a turning point—there is no legitimate lookahead.

What you **cannot** do without OHLC: candlestick pattern recognition, wick rejection, true range, ATR-based stops, intraday breakout timing, or “touched but held” support that never appeared in the fixing. Do not import those tools as if closes were proxies for bars. Null stays null; guessing fills is fabricating evidence.

What closes **do** support: trend persistence measured by stacked averages and swing sequence; momentum agreement or conflict via RSI and MACD; compression and expansion of close-to-close volatility; and break/fail cycles defined by **closes** through close-derived range bounds.

---

## Trend and Dow-style swing structure (no lookahead)

In classical Dow theory, an uptrend is a sequence of **higher highs and higher lows**; a downtrend is **lower highs and lower lows**; otherwise the market is in **range**. On closes only, a swing high is a date whose close is greater than closes on adjacent decision dates you already have; a swing low is the mirror image. A swing is **confirmed** only when subsequent closes show that the extreme held—meaning you label swings **after** the fact, never using tomorrow’s close to justify today’s label.

Until enough swings exist, call trend **insufficient** rather than forcing a narrative. When swings align:

- **Uptrend:** material swing lows rise; rallies exceed prior swing highs.
- **Downtrend:** swing highs fall; sell-offs break prior swing lows.
- **Range:** highs and lows overlap in a band without sustained progression.

Trend is a **description** of recent structure, not a guarantee of the next five fixes. Ranges can persist for weeks; trends can end with a single close through a defended swing on the adverse side.

*Schematic, not a historical episode:* imagine closes stepping from 1.0800 to 1.0920 over many sessions with shallow pullbacks that never close below 1.0850. After the third higher low is visible in the rearview mirror, you may call structure **up**, while still asking whether momentum tools agree.

---

## Moving averages: 20, 50, and 200 sessions

Use simple moving averages on closes: **20** (roughly one trading month), **50** (intermediate), **200** (slow anchor). Read them together:

**Stack.** In a healthy uptrend, close often sits above SMA20, which sits above SMA50; in a strong mature trend, SMA50 may also sit above SMA200. The opposite stack favors downtrends. A broken stack—e.g., price above SMA20 but SMA20 below SMA50—signals transition or range, not a clean continuation template.

**Slope.** A rising SMA20 with rising SMA50 reinforces up; falling slopes reinforce down. Flat 200-day averages often coincide with macro range conditions in major crosses.

**Close versus average.** Repeated closes on one side of the 20-day average show near-term control; rejection back through the 20 after an extension can be early warning of mean reversion within a larger trend.

**Lag.** Averages trail price. A “golden cross” (SMA50 crossing above SMA200) is a **label** for a slow state change that may already be partly in the price. It is not an entry signal by itself and not permission to ignore disagreement elsewhere.

---

## RSI(14), Wilder smoothing

RSI here is 14-period Wilder on closes. It measures recent up-close versus down-close momentum on a 0–100 scale.

### RSI above 70 is NOT automatically bearish

In a **persistent uptrend**, RSI can sit above 70 for extended stretches because winning days dominate. That often indicates **strong momentum**, not an imminent top. Treating every overbought reading as a short signal is how close-only traders fade central-bank-led trends and die slowly.

Similarly, RSI below 30 in a **persistent downtrend** is not automatically bullish. Oversold can stay oversold.

Use RSI as:

1. **Agreement or disagreement** with trend and MACD (see below).
2. **Extension warning**—price may be stretched relative to recent closes; risk management tightens, but direction bias still comes from structure.
3. **Context for no-trade** when combined with conflicting MACD or broken stack—not as a stand-alone reversal command.

When RSI is extreme **with** trend, any trade should **align** with trend unless you have independent structural invalidation—and even then the default playbook answer is often smaller size or no trade, not heroic fading.

---

## MACD(12, 26, 9) on closes

MACD is the difference between 12- and 26-session EMAs of closes; the signal line is a 9-session EMA of MACD; the **histogram** is MACD minus signal.

Read the histogram’s **sign** relative to declared trend:

- Uptrend with positive histogram: **agreement** (momentum supportive).
- Uptrend with negative histogram: **conflict**—price structure says up, momentum engine says cooling.
- Downtrend with negative histogram: agreement.
- Downtrend with positive histogram: conflict.

The line/signal crossover is a slower descriptive event; the histogram is your primary close-only momentum conflict flag for 5D/20D work.

---

## Close-based support and resistance

Without wicks, “support” and “resistance” are bounds from **closes only**:

- **20-close band:** minimum and maximum close over the last 20 sessions.
- **60-close band:** same over 60 sessions.

These are **not** intraday highs/lows and **not** options barriers. A level is “tested” when a **close** nears or pierces the bound. The upper 20-close maximum is overhead resistance in context; the lower 20-close minimum is support. The 60-close extrema frame wider auction memory.

When declaring entries, targets, or invalidations, prefer levels that already appear in this close-range evidence or in confirmed swing closes—not invented intraday prints.

---

## Breakouts, false breaks, and ranges

A **breakout** (close-defined) is a decision close through the relevant 20-close bound in the direction of the break (flags: breakout up/down on the research block).

A **failed break** is information: price closed through the level, then a later decision close moved **back through** the level in the opposite direction (failed breakout flags). Failed breaks sometimes precede sharp moves the other way; sometimes they are noise in a continuing range. They are **not** a mandate to fade every subsequent breakout attempt.

In **range**, expect overlapping 20-close bands, flat SMA50, and mixed MACD histogram signs. Trade only when you have a clear close-level plan with reward exceeding risk; otherwise **no-trade** is the professional outcome.

---

## Volatility regimes (20 vs 60 close-to-close realized vol)

Compare short-horizon realized volatility (20 closes) to a longer baseline (60 closes):

- **Compressed:** 20-day vol materially below 60-day. Energy can build; direction is **not** gifted. Watch for breakout from range, not for a coin-flip long/short.
- **Expanded:** 20-day vol above 60-day. Moves are larger per session; noise grows. Without clear trend or fresh breakout structure, **stand aside**—expanded vol without structure is a no-trade class condition.
- **Normal:** no special veto.

Compression is a precondition watch, not a signal. Expansion demands respect for gap risk in fixing space (weekends/holidays can jump between observations).

---

## Disagreement: the default is no-trade or smaller expression

Define **disagreement** when:

- Trend is up but MACD histogram is negative, or trend is down but histogram is positive; or
- RSI is ≥ 70 inside an uptrend (extension/conflict zone for new trend-following expressions—not automatic reversal, but not clean agreement either); or
- Stack, trend label, and momentum trilogy point different ways.

When stories conflict, **do not** mash them into one heroic trade. Preferred actions:

1. **NO_TRADE** with explicit conflict string in your read.
2. If policy forces engagement, **reduce** size and shorten horizon—never full risk on a contradiction.

Qualification cases labeled `disagreement` or `no_trade` require **NO_TRADE** responses. That is by design.

---

## Entries, invalidation, targets, and exits

**Entry** only on the **decision close** (today’s fixing) or a **pre-declared nearby close level** already visible in the evidence—e.g., yesterday’s close, a 20-close bound, or a confirmed swing close you cited before the decision. Do not invent intraday fills.

**Invalidation** sits on the **adverse** side of the idea:

- Long base: below the defended swing low, below the relevant 20-close support, or below the level whose break would negate the breakout story—whichever you declared when writing the thesis.
- Short base: above the swing high or 20-close resistance analog.

**Target** at the next close-range level (e.g., opposing 20-close bound) or a multiple of the risk distance (reward distance must exceed risk distance before the trade is **worth taking**; otherwise no-trade).

**Exit realism:** mark at the decision close on the declared horizon—**5 sessions** or **20 sessions** after entry—not hypothetical midday profit taking. If the path hits target or invalidation on an intermediate close, that is a realized outcome on the daily mark.

---

## Risk/reward and position size

Before `TRADE`:

1. Measure **risk** as absolute distance from entry close to invalidation close.
2. Measure **reward** as absolute distance from entry to target.
3. Require **reward > risk**. Equal or worse is **no-trade**.

**Position size:** fixed fraction of NAV divided by the close distance to invalidation (risk per unit). No model-implied win probabilities, no Kelly optimization theater, no “70% RSI means bet big.” Size flows from stated risk distance and book policy, not from oscillator myths.

---

## Context horizons: 1D and 10D versus 5D and 20D

**5D and 20D** are primary **holding and evaluation** horizons for Chart Guy expressions.

**1D** (last session return) and **10D** (two-week close path) are **context**:

- Is the 5D idea already extended after a vertical 10D run?
- Did last session’s close gap disturb the stack without invalidating structure?
- Is short-horizon noise elevated in expanded vol?

They are not substitutes for declaring 5D vs 20D intent. A good 20D structural long can still show a negative 1D; that is path noise unless it breaks invalidation.

---

## Executable universe and cross-asset context

**Executable:** spot G10 crosses with ECB (or equivalent) daily closes—EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF, NZDUSD, etc.

**Context only:** rates, equities, commodities when the frozen research packet shows **aligned observations** with explicit publication-lag and roll caveats for futures-linked series. Context may explain why a fixing moved; it **never overrides** the FX technical read and **never becomes** the traded leg unless your seat is authorized for that instrument separately.

If the shared block omits a context series, its story is **unknown**, not bearish by absence.

---

## Explicit exclusions until real OHLC exists

Do not use in rationale or qualification responses:

- Japanese candlestick pattern names (doji, hammer, engulfing, …)
- ATR, true range, wick rejection
- Intraday stop logic or synthetic historical candles built from guesses

Violations fail qualification (`excluded_technique`).

---

## Reading the shared `FX_TECHNICAL_RESEARCH` block

The research artifact is **evidence**, not an order to trade. Expected shape:

- **`market_status`:** coarse health of the technical read (data present, regimes, etc.).
- **Setups (≤10):** includes trend continuation, breaks, failures, range notes, **disagreement**, and explicit **no-trade** templates. Each setup should cite close-only facts.
- **`trade_recommendation`:** always **null** for Chart Guy—human or qualification layer decides.

A **missing** technical block does not veto unrelated bookable trades handled by other seats; it only means this channel had nothing to add.

When consuming the block, map fields to playbook sections: trend, stack, RSI agreement, MACD histogram sign, vol regime, breakout/fail flags, close-range levels. If a field is null, carry null forward—do not backfill from memory or other markets.

---

## Qualification response discipline (training alignment)

Blind cases supply cutoff indicators only. Your response must:

- Match `case_id` and pair; set `cites_post_cutoff` false; `uses_ohlc_atr_candles` false.
- Never embed forward closes in rationale (5D/20D outcomes are for scoring holdouts, not for narrative cheating).
- Populate `indicator_read` honestly: trend label (map missing trend to **insufficient**), `rsi_not_automatically_reversal` when RSI is extreme with trend, `macd_agrees_with_trend` per histogram sign rules, `conflict` when applicable.

If the case `setup_class` is `disagreement` or `no_trade`, answer **NO_TRADE** with all trade fields null.

If you answer **TRADE**, declare horizon **5D** or **20D**, direction consistent with trend for continuation/breakout classes, entry at decision close (within 0.5%), invalidation on the adverse side, target favorably placed with **reward > risk**.

---

## Workflow on a decision date (checklist)

1. Record decision close and observation date from indicators.
2. State trend (or insufficient) from swings + stack.
3. Note 20/60 close-range bounds and whether today’s close broke or failed them.
4. Read RSI for agreement/extension; **do not** auto-fade extremes.
5. Read MACD histogram vs trend.
6. Read vol regime; if expanded with no structure, favor no-trade.
7. If disagreement, stop—or document reduced size with explicit conflict string.
8. If trading, write entry, invalidation, target, horizon; verify reward > risk; size from NAV rule.
9. Separate facts (prints, levels, flags) from inference (bias) from unknown (nulls).

---

## Schematic risk-reward sketch

*Schematic, not a historical episode:* decision close 1.1000 long continuation thesis; 20-close support at 1.0940; next resistance band near 1.1080. Risk 60 pips, reward 80 pips—meets reward > risk. Invalidation is a **close below 1.0940**, not “1.0945 because it feels tight.” If resistance were only 1.1030 (30 pips reward), **no-trade**.

---

## Mental models to avoid

- “RSI 72, must short.” → fade trap in trends.
- “MACD crossed, full size.” → lagging description.
- “Failed break, always fade next break.” → overfit.
- “Vol compressed, buy straddle mentality on direction.” → compression is not direction.
- “USDJPY wick held 150.” → you don’t have the wick.

---

## Pair conventions and quoting

State the base and quote currency on every trade. **Long base** means you expect the cross to rise in fixing terms (e.g., long EUR in EURUSD is long euros against dollars). **Short base** is the opposite. Your entry, invalidation, and target are always quoted in the cross convention used in the case packet—do not flip mid-rationale.

Pip distances for G10 majors are inferred from the quote’s traditional scale (four decimals plus fractional pip for most dollar-quoted majors, two decimals for USDJPY-style quotes). When reward and risk are compared, use the same quote precision as the supplied closes; do not round away a relationship that determines pass/fail on a qualification ticket.

---

## When closes disagree with your bias

A single adverse close does not necessarily end a 20D thesis if invalidation has not been hit. Conversely, a single favorable close does not prove a breakout if the close remains inside the 20-close band. Require **session consistency** for tactical changes: e.g., two consecutive closes back inside the band after a breakout attempt before relabeling a break as failed—unless the research flags already encode the failed-break boolean on the decision date. Trust the shared flags over improvised bar-by-bar reinterpretation.

If the ECB fixing is unchanged for a holiday but your mental calendar advances, **do not fabricate** a synthetic close. Wait for the published observation; until then, indicators for that pair may be stale or null. Staleness is a reason to shrink conviction or stand down, not to interpolate.

---

## Closing principle

The Chart Guy edge in close-only G10 is **discipline**: identical inputs each day, no fabricated intraday detail, honest conflict handling, and expressions sized to fixing-level uncertainty. When the story is clean and reward clears risk, trade the declared horizon. When it is not, the correct output is **NO_TRADE** with a short rationale. That is successful work, not a failed day.
