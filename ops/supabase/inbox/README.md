# Market Watch Supabase inbox

This directory is the narrow handoff from the public Market Watch refresh to the service-side Supabase writer.

`latest.json` is the only automated trigger file. It may contain **public normalized feed state only**. Never put secrets, paid/private research, Gmail/Drive/Notion URLs, raw evidence pointers, or proprietary market data here.

Updating `latest.json` on `main` triggers `.github/workflows/persist-supabase-feed.yml`. That workflow runs `scripts/persist_market_watch.py` using the repository secret `SUPABASE_DB_URL`, performs idempotent sequential writes into the existing private `market_watch` schema, and verifies the final run/item counts.

Required root shape:

```json
{
  "schema_version": 1,
  "public_only": true,
  "run": {
    "run_kind": "news_refresh",
    "window_start": "2026-09-13T10:50:00Z",
    "window_end": "2026-09-14T10:50:00Z",
    "requested_by": "market-watch-daily-refresh",
    "source_scope": {
      "scope": "USD/CAD/AUD/NZD V0 gated refresh"
    }
  },
  "items": [
    {
      "content_type": "news",
      "headline": "Example public headline",
      "summary": "Concise factual summary.",
      "market_read": "Separate market interpretation.",
      "published_at": "2026-09-14T10:00:00Z",
      "observed_at": "2026-09-14T10:50:00Z",
      "country_codes": ["US"],
      "primary_category": "monetary_policy",
      "secondary_categories": ["rates", "fx"],
      "institution": null,
      "author_or_account": null,
      "source_name": "Reuters",
      "canonical_url": "https://www.reuters.com/example/",
      "external_id": null,
      "content_fingerprint": "deterministic_unique_fingerprint",
      "verification_status": "single_source",
      "market_impact": "high",
      "is_top_driver": true,
      "is_last24": true,
      "is_active": true,
      "raw_evidence_url": null,
      "lineage": {
        "admission_score": 8
      },
      "evidence": [
        {
          "evidence_type": "media_report",
          "source_name": "Reuters",
          "source_url": "https://www.reuters.com/example/",
          "published_at": "2026-09-14T10:00:00Z",
          "source_account": null,
          "source_registry_ref": null,
          "is_primary": true,
          "notes": "Public source used for the adopted feed item."
        }
      ]
    }
  ]
}
```

The writer rejects private-host URLs and non-public raw-evidence pointers before opening a database connection. `content_fingerprint` plus `(content_item_id, source_url)` uniqueness make retries idempotent.
