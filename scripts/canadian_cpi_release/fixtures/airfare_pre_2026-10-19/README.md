# Air transportation CPI fixture (pre-2026-10-19)

Separate from the main B2 `pre_2026-10-19` snapshot so the canonical collector hash stays unchanged.

- **Index:** StatCan table 18-10-0004, vector `41691151`, coordinate `2.199.0.0.0.0.0.0.0.0` (Canada, air transportation, NSA).
- **Weight:** table 18-10-0007, vector `91859102`, coordinate `1.183.1.1.0.0.0.0.0.0` (weight at basket link month prices).
- **Retrieved:** 2026-10-18T12:00:00Z live WDS verify + fetch.
- **Cube end:** 2026-08-01 (no September 2026 index point in source).
- Raw JSON under `raw/`; `manifest.json` records sha256 and provenance.
