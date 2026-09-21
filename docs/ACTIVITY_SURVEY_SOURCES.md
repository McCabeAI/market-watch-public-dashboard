# Activity survey sources (V1)

Window: **2025-09 through 2026-09** (as-of 2026-09-21).

## United States (scored)

| Component | Canonical series | Publisher | LEVEL / IMPULSE | History |
|---|---|---|---|---|
| `services_surveys` (28%) | ISM Services PMI headline | ISM | 3m mean / 1m delta | 12 months via [PR Newswire ISM feed](https://www.prnewswire.com/news/institute-for-supply-management/) |
| `manufacturing_surveys` (12%) | ISM Manufacturing PMI headline | ISM | 3m mean / 1m delta | Same |

Gap: **2026-09** not yet released (`not yet released`).

## Canada (not scored)

| Role | Series | Status |
|---|---|---|
| **Target scored** | CFIB Monthly Business Barometer national index | Public monthly page + Excel from 2026-04 onward; national index row empty after questionnaire change — needs manual headline harvest from monthly PDF/summary before scoring |
| **Not scored** | S&P Global Canada Composite PMI | Primary portal not batch-reproducible from this environment |
| **Conflict / corroboration** | Ivey PMI | `source inaccessible` (site); stored only if harvested under non-scored `series_id` |

Calibration documents CFIB 50-neutral convention vs PMI 50-diffusion; do not map Ivey into LEVEL when CFIB is the scored series.

## Australia (not scored)

| Series | Publisher | Status |
|---|---|---|
| Judo Bank / S&P Global Australia **Composite PMI** headline | S&P Global / Judo Bank press releases | `source inaccessible` for monthly history (JS portal); single-release URLs exist but not a full window |

## New Zealand (not scored)

| Series | Publisher | Status |
|---|---|---|
| BusinessNZ **PCI** (GDP-weighted composite) | BusinessNZ / BNZ | `source inaccessible` (Cloudflare); PCI pages exist but not batch-harvested |

ANZ Business Outlook is context only, not the scored PCI series.
