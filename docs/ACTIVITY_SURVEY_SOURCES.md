# Activity survey sources (V1.1 harvest)

Window: **2025-09 through 2026-09** (as-of 2026-09-21).
Canonical scored values are taken from **primary publisher / co-publisher public releases**. Trading Economics and other aggregators are not scored.

LEVEL for scored monthly surveys is the **3-month average** of the headline/composite diffusion index. IMPULSE is the **latest monthly print versus the prior available monthly print**.

## United States (scored)

| Component | Canonical series | Publisher | LEVEL / IMPULSE | History |
|---|---|---|---|---|
| `services_surveys` (28%) | ISM Services PMI headline | ISM | 3m mean / 1m delta | 12 months via official ISM PR Newswire releases |
| `manufacturing_surveys` (12%) | ISM Manufacturing PMI headline | ISM | 3m mean / 1m delta | Same |

Gap: **2026-09** not yet released.

## Canada (scored)

| Role | Series | Status |
|---|---|---|
| **Scored** | S&P Global Canada **Composite PMI Output Index** | Primary monthly Services PMI PDFs (composite section). 9 months: 2025-08 lookback + 2025-09 through 2026-05. |
| **Conflict / corroboration** | Ivey PMI (seasonally adjusted) | Official `https://iveypmi.uwo.ca/` chart payload (`series_id` `Ivey_PMI_conflict`). **Not scored.** |
| **Not scored** | CFIB Business Barometer | Public, but it is a 12-month *outlook* index, not a contemporaneous composite PMI. Not used as a silent PMI substitute. |

Gaps: 2026-06, 2026-07, 2026-08 (`source inaccessible` — primary PDF not retrieved); 2026-09 not yet released.

Portal: [S&P Global PMI press releases](https://www.pmi.spglobal.com/Public/Release/PressReleases).

## Australia (scored)

| Series | Publisher | Status |
|---|---|---|
| S&P Global / Judo Bank Australia **Composite PMI** Output Index | S&P Global / Judo Bank press-release PDFs | Finals: 2025-10–2025-12, 2026-02–2026-03; January 2026 restated as 55.7 in the February flash prior; **July 2026 flash 52.6** (`revision_status: preliminary`) |

Gaps: 2025-09, 2026-04, 2026-05, 2026-06, 2026-08 (`source inaccessible`); 2026-09 not yet released. June 50.4 appears as the prior in the July flash PDF but is **not scored** because June’s own primary file was not harvested.

## New Zealand (scored)

| Series | Publisher | Status |
|---|---|---|
| BNZ–BusinessNZ **PCI GDP-weighted** (PMI+PSI composite) | BusinessNZ / BNZ | Seasonally adjusted GDP-weighted index from BNZ co-publisher PSI PDFs, 2025-09 through 2026-04 |

BusinessNZ HTML (`businessnz.org.nz/psi/…`) is Cloudflare-blocked in this environment (HTTP 403). BNZ Markets Research PDFs are the legally public co-publisher files of the same PCI tables.

Gaps: 2026-05 through 2026-08 (`source inaccessible`); 2026-09 not yet released. ANZ Business Outlook is context only.
