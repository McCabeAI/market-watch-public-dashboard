# Market Watch Public Dashboard

Public dashboard and operational data layer for Market Watch.

- Live dashboard: https://mccabeai.github.io/market-watch-public-dashboard/
- Canonical technical runbook: [`docs/OPERATING_ARCHITECTURE.md`](docs/OPERATING_ARCHITECTURE.md)
- Active light daily refresh specification: [`docs/DAILY_REFRESH_V0.md`](docs/DAILY_REFRESH_V0.md)
- Live 1–100 score state: [`data/temperature_scores.json`](data/temperature_scores.json) (calibrated LEVEL + separate IMPULSE), computed by [`scripts/temperature_level.py`](scripts/temperature_level.py) from [`data/temperature_calibration.json`](data/temperature_calibration.json) and applied by [`scripts/apply_temperature_scores.py`](scripts/apply_temperature_scores.py)
- Standalone daily rates/FX research snapshot: [`docs/MARKET_STATE_FEED_V1.md`](docs/MARKET_STATE_FEED_V1.md)
- Supabase schema migrations: [`supabase/migrations/`](supabase/migrations/)
- GitHub Pages build/deploy gate: [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml)
- On-demand Trader Room entrypoint: [`scripts/trader_room_go.py`](scripts/trader_room_go.py) (`go`); contract: [`docs/TRADER_ROOM_ON_DEMAND.md`](docs/TRADER_ROOM_ON_DEMAND.md)
- Overnight production pipeline (one `overnight_run_id`, 14-seat $100m-paper-NAV risk-capital books, Pages publication gate): [`docs/OVERNIGHT_PIPELINE_V1.md`](docs/OVERNIGHT_PIPELINE_V1.md)
- Four-PM layer above the 14 seats ($1bn-paper-NAV risk-capital books, ChatGPT ingest, review packets): [`docs/PM_LAYER_V1.md`](docs/PM_LAYER_V1.md)

The light V0 daily refresh is the current operational path for news, central-bank research, quick macro data and the 1–100 score panels. Where older runbook language still describes automation as planned, `docs/DAILY_REFRESH_V0.md` is authoritative for this active lightweight workflow.

For storage ownership, data sources, ingestion rules, X archive handling, provenance, refresh steps, validation, rollback, and current limitations, read the operating architecture before changing the system.
