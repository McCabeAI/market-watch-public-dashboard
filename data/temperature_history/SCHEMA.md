# Temperature history observation schema (G0)

Status: G0 backfill contract. Country agents collect observations only; they do not score.

Window: **2025-09-21 through 2026-09-21**, plus the complete set of official releases whose reference period or release date covers that interval. One extra pre-window observation may be stored per series when required to compute a first difference / y/y / annualized rate; mark those `calibration_lookback: true`.

Do **not** invent missing values. Explicit `gaps` are required.

## Files

- `data/temperature_history/us.json` — United States
- `data/temperature_history/ca.json` — Canada
- `data/temperature_history/au.json` — Australia
- `data/temperature_history/nz.json` — New Zealand
- Optional raw downloads under `data/temperature_history/raw/<country>/` (CSV/JSON as retrieved)

## Country file shape

```json
{
  "country": "US",
  "window": {"start": "2025-09-21", "end": "2026-09-21"},
  "retrieved_at": "ISO-8601 UTC",
  "notes": "short coverage narrative",
  "components": {
    "Inflation.core_pce": { "...component object..." }
  }
}
```

Component keys MUST be `{Dimension}.{registry_component}` matching `data/score_source_registry.json`.

US Inflation also includes `Inflation.mapped_bridge` even though it is not a fixed ledger weight.

## Component object

```json
{
  "dimension": "Inflation",
  "component": "core_pce",
  "canonical_name": "human readable series name",
  "publisher": "BEA",
  "distributor": "FRED",
  "series_id": "PCEPILFE",
  "cadence": "monthly",
  "units": "index 2017=100",
  "preferred_scoring_transformation": "mom_sa_annualized_from_index",
  "sa": true,
  "source_urls": ["https://..."],
  "original_authority_url": "https://...",
  "retrieval_method": "fredgraph.csv",
  "methodology_breaks": [],
  "observations": [],
  "gaps": [],
  "coverage": {
    "expected_periods_in_window": 13,
    "observed_periods_in_window": 12,
    "latest_reference_period": "2026-07",
    "latest_release_date": "2026-08-29",
    "status": "ok | partial | unavailable"
  }
}
```

## Observation object

Required fields:

- `reference_period` (YYYY-MM, YYYY-Qn, or ISO date)
- `value` (number) **or** omit value and put the row in `gaps`
- `units`
- `transformation` (what the value actually is: `index_level`, `mom_sa_pct`, `yoy_pct`, `saar_pct`, `thousands_sa`, `diffusion_index`, `percent`, etc.)
- `publisher`
- `source_url`
- `vintage` (`latest_available` unless a true vintage download was used)
- `retrieved_at`

Optional but required when available:

- `release_date`
- `revision_status` (`preliminary`, `revised`, `final`, `unknown`)
- `raw_level` if `value` is a derived transform
- `notes`
- `calibration_lookback` (boolean)
- `series_id`

## Gap object

```json
{
  "expected_period": "2026-09",
  "reason": "not yet released | proprietary no free history | source inaccessible | methodology unresolved",
  "attempted_sources": ["url or publisher"],
  "as_of": "2026-09-21"
}
```

## Rules

1. Official statistical agencies and central banks are the starting authority. FRED/ABS.Stat/StatCan tables/Stats NZ Infoshare may distribute **the same official series** with original publisher retained.
2. Proprietary surveys (ISM, Ivey, Westpac-MI, ANZ, BusinessNZ, Conference Board, Michigan) may be used only if a maintained public/FRED/official reprint exists. Otherwise record an explicit gap. Do not scrape paywalled PDFs into fabricated numbers.
3. Dashboard `data/temperature_scores.json` event bases are **cross-checks**, not a substitute for a sourced time series. A single latest print from the live ledger may be recorded only when the official source URL is also recorded and no earlier history is available; still list earlier expected periods as gaps.
4. Do not silently splice two incompatible series across a methodology break. Record the break.
5. Do not score, weight, or map to 1–100 in these files.
