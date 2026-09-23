# Google Drive raw-archive plan

Status: **documented, not connected.**

Market Watch already treats GitHub as the live technical source of truth for production temperature scores, Notion as operational metadata, and Google Drive as the raw archive when practical. This change does not add a Google credential, OAuth client, service account, sync workflow, or Drive API call.

## What would be archived

| Repo prefix | Drive folder (proposed, not created) | Contents |
| --- | --- | --- |
| `data/macro_ingestion/raw/{country}/{series_id}/` | `Market Watch / macro-ingestion / raw / {country} / {series_id}` | Exact response bytes, named `{checked_at}-{sha256}` |
| `data/temperature_history/raw/{country}/` | `Market Watch / temperature-history / raw / {country}` | Existing committed primary workbooks, PDFs, and harvest reports |
| `data/macro_ingestion/post_freeze/` | `Market Watch / macro-ingestion / post-freeze` | Timestamped post-01:50 ET deltas |
| `data/macro_ingestion/health/` | `Market Watch / macro-ingestion / health` | Per-series check ledger |

## Rules

- Archive the primary bytes and the vintage sidecar. Do not archive a derived score as if it were the source.
- The GitHub object stays canonical for anything the scorer reads. Drive is a recovery copy.
- A missing Drive upload is `archive_status=not_exported_no_credentials`. It is not a successful archive and it does not fail a source check that otherwise retrieved the primary file.
- Notion pages named in the job (Researcher Data Contract, Storage & Persistence Rules, operating hub) are governing context. This repository change does not write to them.
- No Supabase table, migration, or inbox schema is added for this feed.

## Export manifest

`data/macro_ingestion/drive_export_manifest.json` is a list of repo paths with `archive_status`. The shared platform may create that file with every entry set to `not_exported_no_credentials`. It must not contain secrets or a signed URL.
