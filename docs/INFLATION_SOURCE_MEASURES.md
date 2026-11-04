# Inflation source measures (JP and EA scored identities)

This note records the **exact scored series identities** wired through macro ingestion and `data/temperature_calibration.json`. No live vintages were re-fetched for this documentation pass.

## Japan

| Catalog id | Scored series id |
| --- | --- |
| `JP.Inflation.headline` | `CPI_2025BASE_ALL_ITEMS_YOY` |
| `JP.Inflation.underlying` | `CPI_2025BASE_LESS_FRESH_FOOD_ENERGY_YOY` |

The JP adapter (`scripts/macro_ingestion/adapters/jp.py`) selects headline vs underlying from the same e-Stat CPI CSV using `spec.series_id`; there is no headline/underlying swap in adapter mapping.

## Euro area (country HICP)

| Catalog id | Scored series id |
| --- | --- |
| `EA.Inflation.headline` | `PRC_HICP_MINR.M.RCH_A.TOTAL.EA21` |
| `EA.Inflation.underlying` | `PRC_HICP_MINR.M.RCH_A.TOT_X_NRG_FOOD.EA21` |

## EA 2026-10 vs JP 2026-09 in committed history

Committed temperature history can show **EA headline/underlying at 2026-10** while **JP inflation remains at 2026-09**. That gap is a **release-calendar difference** between Eurostat HICP publication timing and the Japan CPI vintage held in history—not evidence that headline and underlying series were exchanged in code, and not a silent re-fetch of live vintages in this change set.
