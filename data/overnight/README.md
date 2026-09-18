# Overnight durable state

Git-auditable JSON is the unattended production store for overnight run ledgers and the 14-seat $100m paper books.

- `books/latest.json` — current locked-seat books
- `latest.json` — pointer at the last assembled morning dataset
- `runs/<overnight_run_id>/` — immutable per-run artifacts
- `inbox/<overnight_run_id>/scheduled_output.json` — untrusted ACP model output awaiting the acceptance gate

This is not a second canonical news/score warehouse. Dashboard news, scores, and Market Data remain on their existing paths.

Supabase is **not** required to ship this pipeline. See `docs/OVERNIGHT_PIPELINE_V1.md` §13 for the migration boundary. Do not put secrets in this tree.
