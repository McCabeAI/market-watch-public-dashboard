create schema if not exists market_watch;

comment on schema market_watch is 'Market Watch Supabase pilot: normalized operational and derived research/news/X state only. Raw evidence remains canonical in Google Drive; canonical normalized numeric history remains spreadsheet-based during the pilot.';

revoke all on schema market_watch from public;
revoke all on schema market_watch from anon;
revoke all on schema market_watch from authenticated;
grant usage on schema market_watch to service_role;

create table market_watch.ingest_runs (
  id bigint generated always as identity primary key,
  run_kind text not null check (run_kind in ('news_refresh','research_refresh','x_refresh','x_archive_import','manual_backfill')),
  status text not null default 'running' check (status in ('running','succeeded','failed','partial')),
  window_start timestamptz,
  window_end timestamptz,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  requested_by text not null default 'agent',
  source_scope jsonb not null default '{}'::jsonb,
  items_seen integer not null default 0 check (items_seen >= 0),
  items_written integer not null default 0 check (items_written >= 0),
  error_summary text,
  created_at timestamptz not null default now(),
  check (window_end is null or window_start is null or window_end >= window_start),
  check (completed_at is null or completed_at >= started_at)
);

comment on table market_watch.ingest_runs is 'Durable job/run state for Market Watch feed refreshes and archive imports.';

create table market_watch.content_items (
  id bigint generated always as identity primary key,
  ingest_run_id bigint references market_watch.ingest_runs(id) on delete set null,
  content_type text not null check (content_type in ('news','research','x_post')),
  headline text not null,
  summary text,
  market_read text,
  published_at timestamptz not null,
  observed_at timestamptz not null default now(),
  country_codes text[] not null default '{}'::text[],
  primary_category text not null,
  secondary_categories text[] not null default '{}'::text[],
  institution text,
  author_or_account text,
  source_name text not null,
  canonical_url text,
  external_id text,
  content_fingerprint text not null unique,
  verification_status text not null default 'single_source' check (verification_status in ('official','corroborated','single_source','unverified')),
  market_impact text not null default 'medium' check (market_impact in ('high','medium','low')),
  is_top_driver boolean not null default false,
  is_last24 boolean not null default false,
  is_active boolean not null default true,
  raw_evidence_url text,
  lineage jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table market_watch.content_items is 'Normalized, derived Market Watch feed items. Not a raw-article archive. Preserve provenance through evidence rows, source URLs, timestamps, and lineage metadata.';

create table market_watch.content_evidence (
  id bigint generated always as identity primary key,
  content_item_id bigint not null references market_watch.content_items(id) on delete cascade,
  evidence_type text not null check (evidence_type in ('primary_source','media_report','official_x','media_x','corroboration','archive')),
  source_name text not null,
  source_url text not null,
  published_at timestamptz,
  source_account text,
  source_registry_ref text,
  is_primary boolean not null default false,
  notes text,
  captured_at timestamptz not null default now(),
  unique (content_item_id, source_url)
);

comment on table market_watch.content_evidence is 'Provenance and corroboration edges for normalized feed items; raw source artifacts remain in their authoritative source or Drive archive.';

create table market_watch.x_follow_snapshots (
  id bigint generated always as identity primary key,
  ingest_run_id bigint references market_watch.ingest_runs(id) on delete set null,
  as_of timestamptz not null,
  imported_at timestamptz not null default now(),
  archive_filename text,
  archive_sha256 text not null unique,
  drive_url text,
  account_count integer check (account_count is null or account_count >= 0),
  notes text
);

comment on table market_watch.x_follow_snapshots is 'Vintage record of exact X-follow snapshots imported from Kevin''s X data archive. The archive file itself belongs in Drive.';

create table market_watch.x_accounts (
  id bigint generated always as identity primary key,
  x_user_id text unique,
  handle text,
  display_name text,
  macro_relevance text not null default 'unclassified' check (macro_relevance in ('core','secondary','ignore','unclassified')),
  institution_type text not null default 'other' check (institution_type in ('central_bank','government','journalist','economist','research','market','commodity','politics','other')),
  primary_category text,
  country_codes text[] not null default '{}'::text[],
  is_market_watch_source boolean not null default false,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  notes text,
  check (x_user_id is not null or handle is not null)
);

comment on table market_watch.x_accounts is 'Resolved X accounts seen in follow snapshots or Market Watch X ingestion. Classification is derived operational state, not raw archive data.';

create unique index x_accounts_handle_ci_uidx
  on market_watch.x_accounts (lower(handle))
  where handle is not null;

create table market_watch.x_follow_memberships (
  snapshot_id bigint not null references market_watch.x_follow_snapshots(id) on delete cascade,
  account_id bigint not null references market_watch.x_accounts(id) on delete restrict,
  raw_entry jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (snapshot_id, account_id)
);

comment on table market_watch.x_follow_memberships is 'Exact membership edges for each X follow snapshot, retaining the raw archive entry needed to audit account resolution.';

create index content_items_published_idx on market_watch.content_items (published_at desc);
create index content_items_type_published_idx on market_watch.content_items (content_type, published_at desc);
create index content_items_category_published_idx on market_watch.content_items (primary_category, published_at desc);
create index content_items_top_driver_idx on market_watch.content_items (published_at desc) where is_top_driver;
create index content_items_last24_idx on market_watch.content_items (published_at desc) where is_last24;
create index content_items_country_codes_gin_idx on market_watch.content_items using gin (country_codes);
create index content_evidence_item_idx on market_watch.content_evidence (content_item_id);
create index ingest_runs_started_idx on market_watch.ingest_runs (started_at desc);
create index x_follow_snapshots_asof_idx on market_watch.x_follow_snapshots (as_of desc);
create index x_accounts_country_codes_gin_idx on market_watch.x_accounts using gin (country_codes);

alter table market_watch.ingest_runs enable row level security;
alter table market_watch.content_items enable row level security;
alter table market_watch.content_evidence enable row level security;
alter table market_watch.x_follow_snapshots enable row level security;
alter table market_watch.x_accounts enable row level security;
alter table market_watch.x_follow_memberships enable row level security;

revoke all on all tables in schema market_watch from anon, authenticated;
revoke all on all sequences in schema market_watch from anon, authenticated;
grant all on all tables in schema market_watch to service_role;
grant all on all sequences in schema market_watch to service_role;

alter default privileges in schema market_watch revoke all on tables from anon, authenticated;
alter default privileges in schema market_watch revoke all on sequences from anon, authenticated;
alter default privileges in schema market_watch grant all on tables to service_role;
alter default privileges in schema market_watch grant all on sequences to service_role;
