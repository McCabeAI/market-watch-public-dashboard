# Activity survey sources (V1.1 harvest, freshness repair)

Window: **2025-09 through 2026-09** (as-of 2026-09-21).
Canonical scored values are taken from **primary publisher / co-publisher public releases**. Trading Economics and other aggregators are not scored.

LEVEL for scored monthly surveys is the **3-month average** of the headline/composite diffusion index. IMPULSE is the **latest monthly print versus the prior available monthly print**.

Deterministic refresh:

```bash
PYTHONPATH=. python3 scripts/harvest_nz_pci.py --cutoff 2026-09-21
PYTHONPATH=. python3 scripts/harvest_ca_pmi.py --cutoff 2026-09-21 --write-ca-json
PYTHONPATH=. python3 scripts/harvest_au_pmi.py --cutoff 2026-09-21 --write-report --write-au-json
PYTHONPATH=. python3 scripts/activity_survey_freshness.py
```

S&P Global `PressRelease/{guid}` endpoints sometimes return HTTP 202 / CloudFront challenge HTML. Harvesters retry `curl_cffi` impersonation (including `safari18_0`), fall back to committed raw PDFs in `data/temperature_history/raw/{ca,au,nz}/`, and, for Australia, Wayback `id_` snapshots. Directory 403s are not treated as source-inaccessible when a direct primary PDF URL succeeds.

Source freshness: `data/temperature_history/activity_survey_release_catalog.json` plus harvest reports must be present in canonical history. A known newer public primary print missing from history fails the source audit. Score weights are unchanged (no staleness decay).

## United States (scored)

| Component | Canonical series | Publisher | LEVEL / IMPULSE | History |
|---|---|---|---|---|
| `services_surveys` (28%) | ISM Services PMI headline | ISM | 3m mean / 1m delta | 12 months via official ISM PR Newswire releases |
| `manufacturing_surveys` (12%) | ISM Manufacturing PMI headline | ISM | 3m mean / 1m delta | Same |

Gap: **2026-09** not yet released.

## Canada (scored)

| Role | Series | Status |
|---|---|---|
| **Scored** | S&P Global Canada **Composite PMI Output Index** | Primary monthly Services PMI PDFs (composite section). 13 months: 2025-08 lookback + 2025-09 through 2026-08. |
| **Conflict / corroboration** | Ivey PMI (seasonally adjusted) | Official `https://iveypmi.uwo.ca/` chart payload (`series_id` `Ivey_PMI_conflict`). **Not scored.** |
| **Not scored** | CFIB Business Barometer | Public, but it is a 12-month *outlook* index, not a contemporaneous composite PMI. Not used as a silent PMI substitute. |

Recovered 2026-06–2026-08 (primary S&P PDFs now in `data/temperature_history/raw/ca/`):

| Period | Composite | Release | Primary URL |
|---|---:|---|---|
| 2026-06 | 47.9 | 2026-07-06 | https://www.pmi.spglobal.com/Public/Home/PressRelease/b407c9ea0281441b9c39f5248f1fc263 |
| 2026-07 | 49.7 | 2026-08-06 | https://www.pmi.spglobal.com/Public/Home/PressRelease/b28d51a7ae54422e9e991e6ea2b06643 |
| 2026-08 | 47.8 | 2026-09-03 | https://www.pmi.spglobal.com/Public/Home/PressRelease/8b925a72bf154a35becc7364eb6e7e58 |

Gap: **2026-09** not yet released.

Portal: [S&P Global PMI press releases](https://www.pmi.spglobal.com/Public/Release/PressReleases).

## Australia (scored)

| Series | Publisher | Status |
|---|---|---|
| S&P Global / Judo Bank Australia **Composite PMI** Output Index | S&P Global / Judo Bank press-release PDFs | Finals through **August 2026 52.7**; July final restated **53.2** in the August PDF (replaces July flash 52.6). June **50.4** is the July-flash restated prior (June's own flash was 49.8). May **48.7** restated in the June flash. April **50.4** final. September 2025 **52.4** restated in the October final. |

Gap: **2026-09** not yet released.

| Period | Value | Status | Primary URL |
|---|---:|---|---|
| 2026-04 | 50.4 | final | https://www.pmi.spglobal.com/Public/Home/PressRelease/3e446e09e41f474a900bdc93ce906d94 |
| 2026-05 | 48.7 | revised (June flash prior) | https://www.pmi.spglobal.com/Public/Home/PressRelease/19b01742d07c4deaa90a63e5d585b150 |
| 2026-06 | 50.4 | revised (July flash prior; June flash 49.8 not scored once restated) | https://www.pmi.spglobal.com/Public/Home/PressRelease/5e210a2556224269a36d74a5288687df |
| 2026-07 | 53.2 | final (August PDF restatement) | https://www.pmi.spglobal.com/Public/Home/PressRelease/1406ace3389f4056ad742043ab5b2e92 |
| 2026-08 | 52.7 | final | https://www.pmi.spglobal.com/Public/Home/PressRelease/1406ace3389f4056ad742043ab5b2e92 |

August flash 52.5 exists at https://www.pmi.spglobal.com/Public/Home/PressRelease/fc9666a5c84d437f94e0fa46202d0aec and is **not scored** because the August final was retrieved.

## New Zealand (scored)

| Series | Publisher | Status |
|---|---|---|
| BNZ–BusinessNZ **PCI GDP-weighted** (PMI+PSI composite) | BusinessNZ / BNZ | Seasonally adjusted GDP-weighted index from BNZ co-publisher PSI PDFs, 2025-09 through **2026-08** |

BusinessNZ HTML (`businessnz.org.nz/psi/…`) is Cloudflare-blocked in this environment (HTTP 403). BNZ Markets Research **directory listing** is also 403; **direct PDF asset URLs** and the BNZ institutional publications index (`/institutional-banking/research/publications`) are public. Repeatable path: `scripts/harvest_nz_pci.py`.

| Period | GDP-weighted PCI | Status | Primary URL |
|---|---:|---|---|
| 2026-05 | 48.5 | revised (no standalone May PSI PDF on the BNZ publications index; August PDF table) | https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf |
| 2026-06 | 51.2 | final (contemporaneous June PDF; August table later shows 51.5) | https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release-June-2026_web.pdf |
| 2026-07 | 51.1 | final | https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_July-2026_web.pdf |
| 2026-08 | 51.6 | final | https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf |

Gap: **2026-09** not yet released. ANZ Business Outlook is context only.
