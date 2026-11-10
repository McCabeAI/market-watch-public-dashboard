# Source ledger (cutoff 2026-11-09)

## SFRI identity

Cotality/CoreLogic **Single-Family Rent Index (SFRI)** is a repeat-pairing MLS rent index for attached homes, detached homes, and condominiums, at national composite and CBSA level. It is **not** the Cotality/CoreLogic home price index (HPI).

Product page: https://www.cotality.com/products/single-family-rent-index — a **sales** product (flat file, cloud, REAS), not a public history. Pricing varies. The page states monthly updates about **three weeks after month-end**. Press methodology states indices are **fully revised with each release**.

**Direct SFRI versus CPI-OER test:** blocked (`provenance/manifest.json`). Minimum acquisition: licensed national SFRI index levels or monthly/yearly changes from 2010 through the latest month available on 2026-11-09, plus real-time vintages or first-print versus current history with publication timestamps; rights must allow private research storage. Explicitly **not** HPI, **not** ZORI, **not** chart reading.

## Observed public press lag

- November 2024 data: press release **2025-01-23** (see `data/press_release_citations.csv`).
- August 2026 CPI: released **2026-09-11** 08:30 ET (BLS September 2026 schedule).
- September 2026 CPI: released **2026-10-14** 08:30 ET.
- August 2026 SFRI-themed press: dated **2026-10-15**, **after** both CPI releases above.

The public press series cannot be a same-month pre-CPI input. A licensed feed at the product-page three-week lag might exist before the following month’s CPI; that timing is an **acquisition requirement**, not a demonstrated delivery fact.

## Warren Pies posts (text only; charts not transcribed)

| Link | Created (UTC) | Notes |
| --- | --- | --- |
| https://x.com/WarrenPies/status/1882548438136651927 | 2025-01-23 21:58 | CoreLogic single-family **rent** index 14-year low; shelter disinflation ahead; contrasts with prior-day NTRR. Same-day press: SFRI November 2024 **1.5% y/y** — SFRI, not HPI. |
| https://x.com/WarrenPies/status/1762296948264972502 | 2024-02-27 02:01 (2024-02-26 US Eastern evening) | January OER vs CPI rent m/m gap largest since 1995; no SF vs MF in text. BLS note: https://www.bls.gov/cpi/notices/2024/rent-oer-information.htm (Jan 2023 OER unit-weight refinement; Jan 2024 detached OER weight share up ~5 pp; rent not reweighted by structure). |
| https://x.com/WarrenPies/status/2001651953080906047 | 2025-12-18 13:53 | Shelter y/y lowest since 2021; CoreLogic SF rents imply more shelter disinflation; **no SFRI number**. Same-day Cotality headline: October 2025 **+0.9% y/y**. |

A claim that a thread said prior-year SFRI flagged shelter stickiness was **not** independently retrieved — **unverified**.

## BLS shelter CPI (frozen in `data/bls_cpi_shelter_through_2026-09.csv`)

| Column | Series ID | Description |
| --- | --- | --- |
| `oer_sa` | CUSR0000SEHC01 | Owners' equivalent rent of primary residence, US city average, SA, Dec 1982=100 |
| `oer_nsa` | CUUR0000SEHC01 | Same, not seasonally adjusted |
| `rent_sa` | CUSR0000SEHA | Rent of primary residence, US city average, SA |
| `rent_nsa` | CUUR0000SEHA | Rent of primary residence, NSA |

**October 2025** is missing (appropriations lapse; stored blank, `missing=1` in build). No interpolation. **October 2026 CPI** is outside this study (scheduled 2026-11-10 08:30 ET).

Retrieval: public BLS API year windows 2012–2021 and 2022–2026 (`scripts/build_inputs.py`). v2 POST honors window bounds; v1 GET alone returns only a short recent tail.

## Zillow ZORI (proxy only)

Definition: https://www.zillow.com/research/data/ — smoothed repeat-rent index, dollar-denominated, stock-weighted, mean of listed rents in the 35th–65th percentile. **Not** CPI stock rent and **not** SFRI.

Snapshot: `data/zori_us_snapshot.csv` — **United States** row only (`RegionName` United States / `RegionID` 102001). Columns `zori_all` (all homes + multifamily) and `zori_sfr` (SFR). Zillow **restates full history** each release; this file is one snapshot, **not** a vintage panel.

## Case–Shiller

Optional FRED `CSUSHPISA` download: `case_shiller_status` in manifest (not used as SFRI or primary OER input).

## Press-release citations

`data/press_release_citations.csv` — bibliographic quotes only, **not** an index. Includes inconsistent **2026-10-15** release and post-cutoff **2026-11-19** announcement row.

## Methodology breaks relevant to OER

- Annual upper-level CPI expenditure weights each January.
- OER structure-type unit weights from January 2023; January 2024 detached-share step.
- Housing survey panels: OER is a **stock-rent** measure, not a new-lease index.
- SFRI and ZORI are new-/repeat-listing market rents and can **lead** the stock compositionally; that mechanism is not, by itself, a one-month print edge.
