create index content_items_ingest_run_idx on market_watch.content_items (ingest_run_id);
create index x_follow_snapshots_ingest_run_idx on market_watch.x_follow_snapshots (ingest_run_id);
create index x_follow_memberships_account_idx on market_watch.x_follow_memberships (account_id);
