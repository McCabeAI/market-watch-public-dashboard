# Portfolio integrator — post-election opportunities

**Written:** 2026-11-05  
**Evidence cycle:** 2026-11-04 (not a blind Nov 4 forecast)  
**Role:** Composer 2.5 scenario and sizing integrator; research only. **ChatGPT decides.**

Reproducible scenario dollars: `scenario_book.py` → `portfolio_scenarios.json`. This memo interprets analyst judgment and those numbers.

---

## Provenance

| Layer | Content |
|--------|---------|
| **Frozen observations** | Commit `612666a21e621e6bb437802cb48ace011f181b7b`, packet SHA `d1a793…3430f`, FX/rates/oil as of 2026-11-03 (and dated legs as in rates/FX notes). |
| **Later CNBC** | Same URL, updated 2026-11-04T17:11Z; narrative yields, quote-table 2Y/30Y, oil “toward” 88/94 — **UNSYNCHRONIZED** vs freeze. |
| **Kevin** | Post-freeze AUDNZD / de-escalation sketch; not verified data. |
| **Deterministic derivations** | `calc_results.json` / `math_notes.md`: CORRA H/M/U/Z, DV01, roll slides, article gaps. |
| **Judgment** | `rates_analyst.md`, `fx_analyst.md` — accepted or rejected below with reasons. |

**Article gaps (not P&L):** narrative 10Y 4.898 vs frozen 4.95 (−5.2bp); 2Y 4.573 vs 4.61 (−3.7bp); 30Y 5.293 vs 5.32 (−2.7bp). Quote table 2Y 4.577 / 30Y 5.29 vs narrative ~−0.4bp / +0.3bp. Oil: 88/96.09−1 ≈ −8.4%, 94/103.60−1 ≈ −9.3%. Use `versus_frozen_cash_yields` for yield comparison — not a tradable mark. Do **not** treat quote-table prints as “frozen” (calc `narrative_vs_quote_table` mislabels them).

**Verified strip (from `calc_results.json`):** CORRA 2027 H/M/U/Z = 2.970 / 3.115 / 3.225 / 3.310; mean **3.155**; cash 2.54; premium **+61.5bp**. Book mark 3.16 vs mean **+0.5bp** (~−$12.5k paper at 25k/bp if remarked — **not** remarking; stored unrealized **$600k**). USDCAD **1.397531…**; CRA **$17.8887/bp/lot**; 349×4 ≈ **$24,973/bp**. SR3 **$25/bp/lot**; SR3 H–Z mean gap vs CORRA H–Z **+34bp / +15bp** on policy paths.

---

## Sign audit: SR3 pay in `calc_portfolio_math.py`

In `pnl_pay_sofr_lots`, pay legs use `−lots × DV01 × shock`, identical to receive. On **common +20bp**, `calc_results.json` shows `futures_pay_4leg_sr3_matched_usd` **−$500,000** and `combined_receive_cra_pay_sr3_usd` **≈ −$999,452** — a **double loss** on parallel rates up.

**Correct convention (implemented in `scenario_book.py`):**

- Receive P&L = **−DV01 × shock_bp**
- Pay P&L = **+DV01 × shock_bp**

DV01-matched overlay on common +20bp is **~flat** (self-check **PASS** at exact match); calc’s combined figure is wrong sign on the pay leg.

**FX skeleton:** `deescalation_escalation_fx_usd_if_present` uses **$250m** notional units — **not** used here. Conditional FX sketches (NZDUSD $30m, CADNOK / EURUSD $40m) are **not** simultaneous book risk.

---

## Ranked proposal

**Proposed book = R0 (equivalently R3 for operations):** **Close** the residual CORRA strip; **no FX** on risk now; **playbook only** for rates and FX conditionals (zero current DV01).

| Rank | Rival | Verdict |
|------|--------|---------|
| **1 (proposed)** | **R0** Flat after close | Zero scenario P&L and zero 30d financing on all assumption paths. |
| **1 (ops twin)** | **R3** Close + conditionals | Same zero risk; documents what would turn on. |
| 2 | R1 Retain 250m receive | Rejected: fails from-flat test; pays ~**$8.2k/30d** financing; large losses on selloff / conflict paths. |
| 3 | R2 U/Z 349s | Rejected: half DV01 does not fix thesis; still wrong expression vs labor/path argument. |
| 4 | R4 Hold-now stub | Considered and **failed**: no READY leg; promoting conditional without marks = R1 with less process. |

**R1 lost vs R0** because ownership, entry 3.40, unfired invalidation, and prior P&L are **not edge**; slack and trim did not bend the path at freeze; null CRA OI; later oil story requires **new** marks before any receive is rational; retaining **~$25k/bp** receive keeps full loss asymmetry on Canada-up / conflict paths (e.g. common +20 net **≈ −$507.7k** after financing in `portfolio_scenarios.json`).

---

## Existing position (mandatory)

| Field | Action |
|--------|--------|
| **ID** | `pm-chatgpt-595561a1b90f` |
| **Instrument** | CORRA 2027 H/M/U/Z equal-weight receive, $250m paper (~**$24,973/bp**) |
| **Decision** | **CLOSE** (not hold, add, or reduce to U/Z) |
| **Fill convention** | Next **common CRA strip mid** — **not** stored mark 3.16 |
| **Execution** | None in this research pass |

---

## Rival scenario P&L (USD, net of 30d SOFR on risk capital)

Financing: **SOFR 3.95% ACT/360** on risk capital = **100 × parallel USD/bp DV01** (1% of $250m mapping at full strip). No evidenced commission. Full grid in `portfolio_scenarios.json`.

### R0 / R3 — flat / playbook (proposed)

All scenarios: **market $0**, **financing $0**, **net $0**. Stated explicitly per instructions.

### R1 — retain full receive (~$24,973/bp; financing **$8,220.15**/30d)

| Scenario | Market | Net (after fin.) |
|----------|--------|------------------|
| Common +20 | −499,452 | **−507,672** |
| Common −20 | +499,452 | **+491,232** |
| CA +25 / US +5 | −624,315 | **−632,535** |
| CA −15 / US −10 | +374,589 | **+366,369** |
| Article −5 / −5 (ASSUMPTION) | +124,863 | **+116,643** |
| Renewed conflict (+20 / +10) | −499,452 | **−507,672** |
| US fiscal long-end (STIR 0) | 0 | **−8,220** |
| Global infl. +15 / +15 | −374,589 | **−382,809** |
| Canada +20 / US 0 | −499,452 | **−507,672** |
| 1Q unchanged roll (ASSUMPTION) | +349,617 | **+341,396** |
| Bull flatten (ASSUMPTION) | +124,863 | **+116,643** |
| Bear steepen (ASSUMPTION) | −62,432 | **−70,652** |

**Roll caveat:** +$349.6k is **assumption** if tenor curve unchanged — **not** expected profit if the thesis is that the priced path is wrong.

### R2 — U/Z only (~$12,486/bp; financing **$4,110.08**/30d)

Same shock labels; magnitudes ≈ **half** of R1 on parallel Canada moves (e.g. common +20 net **≈ −$253,836**). Still loses the from-flat argument with **more** tail in Z premia (+77bp over cash on Z).

### R4 — none held

All zeros; note in JSON.

---

## Conditional playbook (R3 — NOT ON book)

| Idea | Status | Turn-on marks (kill if false) |
|------|--------|-------------------------------|
| New CORRA 4-leg receive ~150 lots/exp (~**$10.7k/bp**) | **CONDITIONAL** | Strip avg within **~5bp of 3.155**; Brent **low–mid 90s** on freeze-family close. **Kill:** avg −15bp from entry, Brent back to 100s, BoC validates mid-3.40s path. |
| SR3 whites receive ~200 lots (~**$5k/bp**) | **CONDITIONAL** | Cash→U7 hike still **~58bp**; same-session **breakevens down** without matching **real-yield rally**. **Kill:** oil mid-90s/100s, core PCE ~3 with hawkish Fed, U7 −15bp without trough move. |
| Long NZDUSD $30m | **CONDITIONAL** | RBNZ 2s/5s/10s + post-election equity/VIX **not** confirming safety-bid selloff; NZ curve **not** easing vs AONIA hike path. |
| Long CADNOK $40m/leg | **CONDITIONAL** | Same-timestamp oil **~−8%** from 96.09/103.60; CADNOK **≤ ~6.6047**. |
| Long EURUSD $40m | **CONDITIONAL** | Spot **≤ 1.1179**; safety bid **not** confirmed in equities/VIX. |
| **Cap if two rates live** | Judgment | Sum **≲ $10k/bp**; prefer CORRA when TIPS split ambiguous. |
| **FX rule** | Judgment | **At most one** cleared FX idea. |

If both rates conditionals were live, **do not** stack to **$25k/bp** — proposed book never holds two receives at full residual DV01.

---

## Idea classification (ready / conditional / rejected)

| Idea | Class |
|------|--------|
| Close `pm-chatgpt-595561a1b90f` | **READY** (rates judgment at freeze) |
| Retain / add CORRA receive | **REJECTED** |
| Reshape U/Z 349s | **REJECTED** |
| Pay H / receive Z flattener | **REJECTED** |
| DV01-matched SR3 pay “hedge” | **REJECTED** |
| US 10Y/30Y receive | **REJECTED** (no TY/WN) |
| Pay AONIA 2028 give-back | **REJECTED** |
| New CORRA 4-leg (150s) | **CONDITIONAL** |
| SR3 whites receive (200 lots) | **CONDITIONAL** |
| AUDNZD long or short | **REJECTED** |
| NZDUSD / CADNOK / EURUSD | **CONDITIONAL** (FX note ranks; none READY on Nov 3 fix) |

---

## Proposed book — component exposures (R0)

| Component | On-book now | Playbook (NOT ON) |
|-----------|-------------|-------------------|
| Growth | 0 | CORRA/SR3 conditionals: mixed; NZD long: long cool growth |
| Inflation | 0 | CORRA: fade priced hikes if oil marks down; SR3: breakeven channel |
| Policy path | 0 | CORRA/SR3 receive if marks confirm |
| Fiscal / term premium | 0 | EURUSD conditional: positioning vs dollar real yields |
| Energy / terms of trade | 0 | CORRA, CADNOK: oil markdown |
| Currency | 0 | At most one FX conditional |
| Liquidity / carry | 0 | SOFR on risk capital only if sized; FX points absent |
| Horizon | Immediate flat | 1–8 weeks if triggered |
| Convexity | 0 | Linear STIR/spot only |

**Correlated legs:** CORRA receive and SR3 receive are **same sign** on parallel nominal selloff — **not** hedges; cap combined DV01. CORRA and CADNOK share **oil/terms** channel but are **not** bundled at zero risk; FX is **at most one** leg.

---

## Regime winners and losers (proposed flat + playbook)

| Regime | Winners (if triggered) | Losers (if triggered) |
|--------|-------------------------|------------------------|
| **De-escalation** (CA−15/US−10, oil down) | Closed book **already** avoids R1 give-back regret; **conditional** CORRA/SR3 **receive** if marks still valid | Any **retained** receive (R1) wins market P&L but was **wrong ex ante**; NZD long if curve/regime clear; CADNOK if oil mark confirms |
| **Renewed conflict** (CA+20/US+10) | **Flat** avoids **~−$507k** (R1 scale); no FX on book | Any live CORRA receive; long NZD/EUR; **not** short NOK chase |
| **US fiscal disappointment (long end)** | Flat: only **−financing** if wrongly still in R1; no STIR expression in rivals | Cash 10Y/30Y would win — **not in book**; SR3/CRA **~0** by construction |
| **Global inflation (+15/+15)** | Flat | Any receive; fiscal-story EUR long hurt by dollar real-yield support |
| **Canada labor/inflation surprise (+20 CA)** | Flat | CORRA receive; partial U/Z still **−~$254k** on +20 |

---

## Timing and sizing rules

1. **Close:** Execute on **next common session** CRA H/M/U/Z settlements (or agreed paper mid). **Do not** use 3.16 as fill. Size change: **to zero** residual DV01.
2. **Gains on conditionals:** CORRA — cover if strip avg **−15bp** from entry or Brent reclaims **100s**; SR3 — exit if U7 **−15bp** without trough move or breakevens snap back; FX — take **~half** at **+1.5–2%** spot per FX note, or oil round-trip for CADNOK.
3. **New risk:** Only after **one common timestamp** satisfying the conditional table; max **one** FX; combined rates **≲ $10k/bp** if two fire.
4. **Kill conditionals without entry:** Strip moved **>5bp** from 3.155 without you; oil not in 90s family; breakeven rule fails; safety bid confirmed in equities/VIX; NZ curve missing or easing vs AU hikes.

---

## ChatGPT decision note

This integrator **aligns with rates (close, no reshape, no SR3 overlay)** and **FX (nothing READY; playbook only)**. Scenario math **disagrees** with `calc_results.json` on **SR3 pay sign**; use **`portfolio_scenarios.json`** for rival grids. Probabilities and fair values were **not** invented.
