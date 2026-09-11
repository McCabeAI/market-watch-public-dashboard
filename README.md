# Market Watch Public Dashboard

Public dashboard and operational data layer for Market Watch.

- Live dashboard: https://mccabeai.github.io/market-watch-public-dashboard/
- Canonical technical runbook: [`docs/OPERATING_ARCHITECTURE.md`](docs/OPERATING_ARCHITECTURE.md)
- Active light daily refresh specification: [`docs/DAILY_REFRESH_V0.md`](docs/DAILY_REFRESH_V0.md)
- Supabase schema migrations: [`supabase/migrations/`](supabase/migrations/)
- GitHub Pages build/deploy gate: [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml)

The light V0 daily refresh is the current operational path for news, central-bank research, quick macro data and the 1–100 score panels. Where older runbook language still describes automation as planned, `docs/DAILY_REFRESH_V0.md` is authoritative for this active lightweight workflow.

For storage ownership, data sources, ingestion rules, X archive handling, provenance, refresh steps, validation, rollback, and current limitations, read the operating architecture before changing the system.
