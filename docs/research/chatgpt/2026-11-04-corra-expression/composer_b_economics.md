# Composer B — Adversarial economics & evidence lineage (CORRA expression)

**Role:** Research-only economics worker for the Nov 4 CORRA expression review.  
**Sources read:** `frozen_inputs.json` only (plus challenge summaries and own-PM memory as instructed in the task brief).  
**Not a blind morning call:** This note is written after the Nov 4 trader session; it is retrospective synthesis on frozen evidence.

---

## Evidence lineage and timing (OBSERVED)

| Item | Value |
|------|--------|
| Review accepted / stated cutoff | `2026-11-04T05:35:22.541505-05:00` |
| Packet SHA256 | `d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f` |
| Agent packet SHA256 | `a524f07cbfdfafdb44d016a2fd9c6abd31aeae6ab261bda0b8beab172ab571a2` |
| Pinned commit | `612666a21e621e6bb437802cb48ace011f181b7b` |
| **Assigned rate snapshot** `market_state_generated_at` | **`2026-11-04T10:52:31Z`** — **after** the stated review cutoff |
| Composite PM packet `market_state` (NOT used) | `2026-11-04T12:12:27Z` |

**JUDGMENT:** Use the 10:52Z snapshot as the assigned freeze per task rules, but **flag ordering**: any narrative that treats “as-of cutoff” and “as-of mids” as simultaneous is wrong. Do not repair the mismatch.

**Book context (memory / OBSERVED on book, not thesis proof):** Residual **250m USD-notional equivalent** long (receive) `CORRA_2027H-Z`, entry mark **3.40** (2026-09-20), book mark **3.16** (2026-11-03, do not replace with research arithmetic). Half of 500m reduced Nov 3. Net after funding ~+1.175m USD is background only.

---

## Question

Can the PM preserve a **real Canadian policy-path edge** with **better expected return and adverse-path behavior** than the current **equal-weight 2027 CORRA receive (H/M/U/Z)**?

Alternatives under test:

- **A.** Retain equal-weight H–Z receive — no-add vs reduce/close vs fresh-from-flat  
- **B.** **Pay Mar 2027 / receive Dec 2027** CORRA, DV01-matched (intra-Canada flattener)  
- **C.** Retain deferred Canada receive vs **DV01-matched SOFR pay** or **AONIA pay** (diversification; simple US–CA curve differential allowed; no four-leg box)

---

## 1. What is actually priced (JUDGMENT + DETERMINISTIC DERIVATION)

**OBSERVED:** CORRA cash/fixing **2.54%** (2026-11-02). Snapshot **3m CORRA** (MX):

| Contract | Expiry | Implied % | Minus cash (bp) |
|----------|--------|-----------|-----------------|
| CRAH27 | 2027-03 | 2.97 | +43.0 |
| CRAM27 | 2027-06 | 3.115 | +57.5 |
| CRAU27 | 2027-09 | 3.225 | +68.5 |
| CRAZ27 | 2027-12 | 3.31 | +77.0 |

**DETERMINISTIC DERIVATION — equal-weight H–Z strip:**

- Average implied rate: **(2.97 + 3.115 + 3.225 + 3.31) / 4 = 3.155%**
- Versus cash 2.54%: **+61.5 bp** average “futures minus overnight” on the held strip  
- Intra-strip slope (Z minus H): **3.31 − 2.97 = +34 bp** across Mar→Dec 2027 quarters  
- Book/journal average **3.16%** (Nov 2 mids 2.96/3.12/3.235/3.325) is **1 bp** above snapshot arithmetic — within rounding / mark timing

**JUDGMENT (required):** **3m futures minus cash is not a meeting path and not guaranteed carry.** Each CRA settles to a **quarter-average** CORRA, not a single policy decision. The **1m CORRA chain** in the freeze runs only through **Feb 2027**:

| Expiry | Implied % | Minus cash 2.54 (bp) |
|--------|-----------|----------------------|
| 2026-11 | 2.515 | −2.5 |
| 2026-12 | 2.605 | +6.5 |
| 2027-01 | 2.655 | +11.5 |
| 2027-02 | 2.785 | +24.5 |

That chain is the **near-term priced object** for front policy repricing; the **H–Z 3m strip** is the **deferred quarter-average** object the book owns. **Exact IMM reference-quarter start/end dates and convexity adjustments are not in** `contract_economics.py` **or the snapshot** — any meeting-count arithmetic would be invented.

**Policy terminal proxy in freeze:** CA Feb 2027 1m **2.785%** (+24.5 bp vs cash in the 1m table; +24.5 bp overnight change field on COAG27).

---

## 2. BoC path, news family, and missing ingest (JUDGMENT + OBSERVED)

**OBSERVED:**

- News family records **Fed hold headlines dated 2026-10-28**; **`boc_decision_record_in_news_family`: false**
- PRiMA `corra_vs_proxy_neutral`: CORRA **2.54**, proxy midpoint **2.75**, gap **−21 bp** — note in freeze: CORRA is the **observed overnight benchmark, not a Governing Council vote**; **2.75 is proxy input, not re-estimated BoC neutral**

**JUDGMENT (required):** The **late-October BoC hike** lives in the PM **Nov 3 hypothesis/journal**, **not** in the Nov 4 news family. Do **not** treat **2.75** as a freshly re-estimated neutral rate.

**Missing common-ingest item (evidence gap):** **Official BoC target decision record** for the late-October 2026 announcement — **decision, effective date, full statement** — needed to align cash, front futures, and any “hike is done vs hike is coming” debate with primary source rather than journal memory.

---

## 3. Macro series definitions (OBSERVED — do not mislabel)

| Series | Frozen meaning | Value / period |
|--------|----------------|----------------|
| CA underlying inflation | **Equal average** CPI-trim and CPI-median **y/y** | **1.85%**, 2026-09 (not headline) |
| CA headline CPI | All-items **y/y** | **3.0928%**, 2026-09 |
| CA unemployment | Published **rate** vs u* | **6.5%** vs anchor **6.0%**, 2026-09 |
| CA employment | **3-month mean m/m change in thousands**, not % | **−11.63k**, 2026-09 |
| CA wages | **y/y %** | **2.3382%**, 2026-09 |
| CA consumer income | **Q2 q/q nominal** | **2.12%** — not a current boom print |
| CA spending | **Q2 q/q real** | **0.8%** |
| CA retail | **3m mean m/m nominal** through 2026-08 | **0.3277%** |
| AU underlying | Trimmed-mean **y/y** vs midpoint | **3.6%** vs **2.5%**, 2026-09 |
| US core PCE | **3-month annualized** through **2026-07**, retrieved 2026-09-21, **carried forward** | **3.0478%** — **not** a fresh y/y |

Labor/inflation **dimensions** in the freeze are composite scores (e.g. CA labor “cooling”, activity “warming”) — useful as **labels**, not as independent market observations.

---

## 4. Oil and pass-through (OBSERVED + JUDGMENT)

**OBSERVED — separate instruments:**

- Compact Brent **103.60** (BZ=F, 2026-11-03) vs WTI **96.09** same date  
- Deferred: **BZZ26 117.64** (obs 2026-10-30), **BZZ27 84.88**, **BZZ28 77.38** (2026-11-03)  
- PRiMA: deferred Brent end-2027 vs July MPR prose **70** → **+14.88 USD/bbl** gap (conditioning 2026-07-09)  
- **IPPI energy mom ~+12.08%**, **RMPI crude mom ~+14.42%** (Sep); **IPPI ex-energy ~+0.28% mom**; **RMPI ex-crude slightly down** — RMPI is **not** an import price index

**JUDGMENT:** Energy is the **strongest factual challenge** to a pure “policy overtightened → cuts priced too little” receive thesis, **without** a verified BoC decision record in ingest. Pass-through can hit **headline CPI (3.09 y/y)** and goods pipelines even while **trim/median (1.85)** stays soft — BoC reaction function is not frozen here.

---

## 5. Breadth and PRiMA shock taxonomy (OBSERVED)

- **CPI breadth:** **5 of 8** major components positive **mom** in September — **NSA monthly breadth**, not a y/y diffusion claim  
- PRiMA: direction **STABLE**, strength **low**, confidence **high**; **front_shock: parallel_upward_repricing**  
- Subcomponents: breadth **RISING**, shock persistence **RISING**, imported-labeled channel **FALLING** (series **not** imports), production network **STABLE**

**JUDGMENT:** Parallel upward repricing in the shock classifier is **consistent with front-end rates backing up globally** in the snapshot (large positive `change_from_overnight_bps` on deferred CORRA and SOFR). That hurts **receive** on mark-to-market even if the **level** still looks rich vs cash.

---

## A. Equal-weight H–Z receive (retain / reduce / close / fresh-from-flat)

### Market-implied path (JUDGMENT)

The strip embeds **~62 bp** average premium of **2027 quarter-average CORRA** over **today’s 2.54%** overnight — i.e. the market pays the PM to **receive** if those averages **realize above** what's priced, and the PM loses if **policy stays higher or reprices higher**. The **+34 bp** H→Z upward slope prices **some** combination of **near-term validation** (front quarters below back) and **later easing** — not fully separable without 1m CRA beyond Feb 2027.

### No-add retain (250m residual)

**For:** Hypothesis rev 04 falsifier is explicit — retain only if **core inflation, wages, employment, BoC communication** do **not** substantiate **additional hikes**; snapshot **underlying 1.85** and **weak employment mean** still lean **cooling** on definitions above. **Reduce already done** (500→250).  
**Against:** Overnight session ** repriced deferred CORRA higher** (+43 to +77 bp vs overnight on H–Z); **parallel_upward_repricing**; **energy/IPPI** channel; **missing BoC record** means the “hike happened” state is **journal-backed**, not ingest-backed. **CORRA OI/volume null** — position is **paper-markable**, not evidenced as exchange-liquid.

**Edge given up by reduce/close:** Any **terminal easing** if the strip **mean-reverts** toward cash from **3.15** area; optionality on **curve bull flattening** in Canada.

### Fresh-from-flat at snapshot

**DETERMINISTIC:** Would initiate receive near **3.155%** strip average vs **3.40%** historical entry — **~24.5 bp less “richness”** already in the trade (before costs).  
**JUDGMENT:** Fresh-from-flat **does not** recover the **Sep entry edge**; it buys the **same macro disagreement** at a **worse level** after adverse mark. **Book P&L is not proof** the thesis is right — only that **rates fell** since entry on the book’s mark convention.

---

## B. Pay Mar 2027 / receive Dec 2027 (DV01-matched flattener)

**DETERMINISTIC:** Receive Z **3.31%**, pay H **2.97%** → **+34 bp** receive-back/pay-front spread per matched CRA lot (CAD 25 DV01 per 0.01 per leg in freeze conventions).

**Mechanism (JUDGMENT):** Wins if **front 2027 quarter average reprices up** (pay leg hurts less than receive leg helps on flattening) **or** **back eases faster** than front — i.e. **H–Z segment flattens**. Loses on **steepening** (more hikes priced in the back, or front cuts faster than back).

**For flattener:** Macro mix of **soft trim/median + weak jobs mean** but **headline/energy risk** supports **near-term hawkish repricing in Mar 2027** while **later quarters** could still embed **easing** — a **story** the slope partially prices (+34 bp).  
**Against flattener (strongest):** If the **receive thesis is right** because **the whole strip is too high**, the **best expression is outright receive**, not **giving up 34 bp** of slope carry to the market. Flattener **caps** participation in **parallel** strip rally (all contracts rally ≈ flattener bleeds). Overnight **parallel_upward_repricing** is specifically **bad** for a new flattener entered **after** the shock.

**Edge given up vs outright:** **Parallel receive** on the full strip; **simplest** expression of “Canada overpriced vs path.”

---

## C. Deferred Canada receive vs SOFR pay or AONIA pay (DV01-matched)

**DETERMINISTIC — US–CA 2027 spreads (3m mids):**

| Point | SOFR − CORRA (bp) |
|-------|-------------------|
| Mar 2027 | 4.365 − 2.97 = **139.5** |
| Dec 2027 | 4.515 − 3.31 = **120.5** |
| Strip avg (approx) | **~132.5** |

**AONIA:** Mar 2027 1m **4.915%** − CORRA H27 **2.97%** = **~194.5 bp**.

**Mechanism (JUDGMENT):** A **CAD receive + USD pay** (or AUD pay) is a **curve-differential** bet: Canada **eases relatively** vs US/AU **or** Canada **was relatively too tight** in futures. It is **not** diversification if the driver is **global energy/inflation repricing** — one shock moves **all** front ends.

**SOFR pay hedge — for:** SOFR **OI large** (e.g. SR3Z7 OI ~1.54m); executable hedge **if** the book could trade it; **SOFR cash 3.95** vs **CORRA 2.54** = **141 bp** cash differential — freeze shows **US front already high** vs CA.  
**SOFR pay hedge — against (strongest):** **Overlapping global inflation beta** (PRiMA parallel shock); if BoC **must hike further on energy**, **US may stay higher for longer** too — **pay SOFR** adds **loss on adverse hawkish global path** while **receive CORRA** also loses → **double hit**. PM memory already **rejected** overlapping US duration for **portfolio pass** reasons; that rejection **does not** prove a **DV01-matched SOFR pay** is wrong — but it flags **correlation risk**.

**AONIA pay hedge — against (strongest):** **AU underlying 3.6** vs **2.5** midpoint — **warm** inflation; deferred IB **OI thin** (Mar 2027 **400** lots, many months **null** OI); **different country ticker is not diversification** under **global repricing**. **Edge given up:** Simplicity of **single-country** policy view; **liquidity** and **basis risk** on ASX vs MX.

**Edge given up vs outright CA receive:** **Pure Canada policy-path alpha** un contaminated by **US/AU terminal rate** moves; **fewer legs**, no **cross-currency DV01** mapping (USD P&L on composites → **contract-math scenario**, not second DV01 here).

---

## 6. Strongest cases AGAINST each alternative

| Alternative | Strongest case AGAINST | Edge given up if you abandon it |
|-------------|------------------------|----------------------------------|
| **Outright H–Z receive** | **Energy + headline CPI + IPPI/RMPI energy jumps** + **parallel upward repricing** already moving against you; **missing BoC decision record** weakens “ hikes done” narrative; **null CORRA OI** | N/A (baseline) |
| **H/Z flattener** | If strip **richness is parallel**, flattener **underperforms** outright receive; **34 bp** slope is **payment** to express a **narrower** view | Full **strip receive** on **mean reversion** of **all** quarters |
| **SOFR pay overlay** | **Global inflation shock** correlation; **SOFR already elevated** — pay leg **negative carry vs path** if US stays firm | **Uncorrelated** Canada-only easing if US diverges down |
| **AONIA pay overlay** | **Thin OI**, **AU inflation warm**, same **global shock** | **Clean CAD** expression |

---

## 7. Already-owned residual vs fresh-from-flat (JUDGMENT)

**OBSERVED:** Entry **3.40** vs snapshot strip **~3.155** — much of the **“strip vs low cash”** edge is **realized in mark** (book 3.16).  
**JUDGMENT:** **Sunk edge** lowers the **marginal expected return** of **adding**; **retain** is a **hypothesis maintenance** decision (falsifier-driven), not re-entry at Sep economics. **Closing** crystallizes **gain + thesis exit**; **not** evidence the world **changed** unless macro/falsifier triggers fire. **Do not** cite **+1.17m net** as **evidence** thesis still holds.

---

## 8. Horizons and carry (JUDGMENT)

- **1–3 months:** Cannot **realize** the **Mar 2027** accrual reference period; **futures vs cash gap** is **not** mechanical carry — it is **mark and roll** under assumptions.  
- **Roll-down:** Exists only under **unchanged tenor curve** — **contract-math worker** measures; not asserted here.  
- **3–6 months:** Still **before** Dec 2027 reference quarter **begins**; P&L is **curve repricing**, not ** realized quarter-average CORRA**.  
- **carry-is-king** trader argument (challenge summary): **near Mar CORRA** has different **liquidity/horizon** than **2027 H–Z** — **no-trade-skeptic** point that **overnight horizon is wrong** for multi-meeting curve has **timing merit** on **carry realization**, not necessarily on **direction**.

---

## 9. Scenario decomposition (JUDGMENT)

| Driver | Effect on receive | Effect on flattener | Effect on US/AU pay hedge |
|--------|-------------------|---------------------|---------------------------|
| **Global inflation / energy repricing** | **Bad** (parallel backup) | **Bad** if parallel | **Bad** (correlated) |
| **Canada-specific pass-through / BoC hawkish** | **Bad** | **Mixed** (may help pay-H) | **Hedge unclear** |
| **De-escalation / oil fade** | **Good** | **Good** if back leads | **Mixed** |
| **Weaker CA domestic demand** | **Good** (easing priced) | **Good** if back falls | **CA leg good; US leg may lag** |

**Liquidity (OBSERVED):** CORRA **OI/volume null**; SOFR **large OI**; AONIA deferred **thin/null**. Existing book is **research/paper** executable quality **unproven** in freeze.

**Consistency check only (OBSERVED):** CA 2Y **3.26%** (Nov 2), US 2Y **4.61%** (Nov 3) — different instrument family; position locked to **CORRA futures**, not govies.

---

## 10. Epistemic limits (explicit)

No fair value model, no probabilities, no confidence intervals, no backtest. SOFR history in freeze: **2026-06-25 → 2026-11-02** cash path only. **CME positioning unavailable**; **do not** treat trader CFTC CAD sentences as facts.

---

## 11. Expression rank (input to parent — not the decision)

**Rank: RETAIN reduced receive (no-add), do not reshape; bias to REDUCE further on falsifier triggers rather than add FX or US duration hedge.**

| Field | Content |
|-------|---------|
| **Mechanism** | Deferred **2027 quarter-average CORRA** still **~62 bp** above **2.54%** cash on equal-weight strip — **overpriced path** vs **soft underlying inflation (1.85)** and **weak employment mean**, **if** no further BoC tightening is **substantiated** |
| **Market-implied path** | **Upward-sloping H–Z (+34 bp)** with **front 1m chain** rising to **2.785%** by Feb 2027 — mixes **near-term firmness** with **later averages higher still** |
| **Horizon** | **6–18 months** to **reference quarters**; **1–3 month** P&L is **repricing**, not accrual realization |
| **Falsifier** | **Close or reduce further** if **core inflation, wages, employment, BoC communication** substantiate **additional hikes**, especially strip **back toward 3.35–3.40** average (hypothesis rev 04) |

**Best objection to this rank:** **Evidence hole on BoC October decision** + **energy/headline/IPPI** + **overnight parallel backup** may mean the **remaining ~24 bp vs entry** is ** insufficient compensation** for **hawkish tail**, and **null CORRA liquidity** makes **“preserve edge”** meaningless outside the paper book — **close** could be **rational** even without falsifier text triggering.

**Alternatives ranked below retain-no-add:**

1. **Reduce further** — beats **flattener** and **cross-market pay** when **global shock correlation** is high and **thesis edge is marked away**.  
2. **Reshape (H/Z flattener)** — **insufficient evidence** that **34 bp** slope is **mispriced vs parallel risk** after **parallel_upward_repricing**.  
3. **SOFR/AONIA pay hedge** — **reject for this PM pass** (correlation + prior portfolio test + AU liquidity); **does not** answer DV01-matched hedge **mathematically**, but **fails diversification** under assigned scenarios.  
4. **Fresh-from-flat add** — **worse level**; no-add preferred.  
5. **Close entirely** — **competitive** with retain if parent weighs **missing BoC ingest** heavily.

---

## Trader challenge cross-check (arguments only, not votes)

- **carry-is-king / rate-dove long CORRA** — aligned with **receive** but often ** nearer tenors** than **H–Z**; horizon mismatch noted.  
- **perma-bull / positioning-cynic / rate-hawk shorts** — stress **adverse backup** narrative consistent with **overnight bp changes**.  
- **no-trade-skeptic / catalyst-junkie / vol-convexity flat** — **CORRA OI null** and **no options surface** support **cannot prove executable edge**.  
- **pragmatist long CORRA Mar + short AUDNZD** — **FX rejected** by PM memory for **regime risk**; not re-litigated here beyond **non-diversifying** macro beta.

---

## Parent summary (one paragraph + three objections)

**Recommendation:** **Retain the 250m equal-weight CORRA 2027 H–Z receive with no adds**, treating the trade as a **hypothesis-maintenance** position at a **marked-down entry edge (~3.16 book vs 3.40 initial)**, not a fresh rich entry; **do not** reshape into an H/Z flattener or SOFR/AONIA pay overlay given **parallel global repricing**, **energy/headline pass-through risk**, and **unproven CORRA liquidity** in the freeze — **reduce or close** if BoC communication and **core labor/inflation** substantiate ** further hikes** or the strip **re-approaches 3.35–3.40** average, over **6–18 month** reference-quarter horizons where P&L is still mainly **repricing**.

**Three strongest objections:** (1) **Missing official BoC late-October decision ingest** leaves the **policy starting line** journal-anchored, not evidence-anchored. (2) **Sep–Nov energy and IPPI/RMPI crude observations** plus **headline CPI 3.09 y/y** are a **credible hawkish tail** not offset by **trim/median alone**. (3) **Overnight parallel upward repricing** and **~24 bp of edge already captured** imply **retain** is **negative expected margin** unless you **believe** further **parallel** backup stops — which the freeze **does not** establish.
