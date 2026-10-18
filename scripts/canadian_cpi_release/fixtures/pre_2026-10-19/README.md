# pre_2026-10-19 snapshot

Frozen Canadian CPI release input set captured **2026-10-18** (`retrieved_at` in `snapshot.json`).

- **StatCan:** WDS `getDataFromVectorsAndLatestNPeriods` batches under `raw/statcan_*.json` and `raw/statcan_weight_*.json` (vectors and `latestN` per `contract.py`).
- **NRCan:** Monthly Canada-average HTML pages `raw/nrcan_*_{year}.html` from `NRCAN_PAGES` URL templates (product 1 gasoline, 7 furnace oil; location 66; 2016–2026).

Official NRCan monthly furnace-oil table has no **2017-08** row; the fixture records all other months in 2016-07..2026-09 without research CSV fill.
