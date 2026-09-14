#!/usr/bin/env python3
"""Persist one public Market Watch feed payload into the private Supabase operational store.

This script is intended for GitHub Actions, not browser/client execution. It uses a
server-side Postgres connection supplied through SUPABASE_DB_URL. Writes are small,
sequential, idempotent, and limited to the existing market_watch operational tables.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

ALLOWED_RUN_KINDS = {"news_refresh", "research_refresh", "x_refresh", "manual_backfill"}
ALLOWED_CONTENT_TYPES = {"news", "research", "x_post"}
ALLOWED_VERIFICATION = {"official", "corroborated", "single_source", "unverified"}
ALLOWED_IMPACT = {"high", "medium", "low"}
ALLOWED_EVIDENCE = {
    "primary_source",
    "media_report",
    "official_x",
    "media_x",
    "corroboration",
    "archive",
}
PRIVATE_HOSTS = {
    "app.notion.com",
    "notion.so",
    "www.notion.so",
    "drive.google.com",
    "docs.google.com",
    "mail.google.com",
}
DEFAULT_PAYLOAD = Path("ops/supabase/inbox/latest.json")


def die(message: str) -> None:
    raise SystemExit(message)


def require_https(url: str | None, field: str) -> None:
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        die(f"{field} must be an absolute HTTPS URL")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in PRIVATE_HOSTS or host.endswith(".notion.so"):
        die(f"{field} points to a private/disallowed host: {host}")


def validate_payload(payload: dict[str, Any], path: Path) -> None:
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        die("payload must live inside the repository")
    if not str(rel).startswith("ops/supabase/inbox/"):
        die("payload must live under ops/supabase/inbox/")
    if payload.get("schema_version") != 1:
        die("schema_version must be 1")
    if payload.get("public_only") is not True:
        die("public_only must be true")

    run = payload.get("run")
    items = payload.get("items")
    if not isinstance(run, dict) or not isinstance(items, list):
        die("payload requires run object and items array")
    if run.get("run_kind") not in ALLOWED_RUN_KINDS:
        die("unsupported run_kind")
    for key in ("window_start", "window_end", "requested_by"):
        if not run.get(key):
            die(f"run.{key} is required")
    if not isinstance(run.get("source_scope", {}), dict):
        die("run.source_scope must be an object")
    if not 0 <= len(items) <= 100:
        die("items must contain 0..100 public feed items")

    seen_fingerprints: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            die(f"items[{idx}] must be an object")
        if item.get("content_type") not in ALLOWED_CONTENT_TYPES:
            die(f"items[{idx}].content_type invalid")
        if item.get("verification_status") not in ALLOWED_VERIFICATION:
            die(f"items[{idx}].verification_status invalid")
        if item.get("market_impact") not in ALLOWED_IMPACT:
            die(f"items[{idx}].market_impact invalid")
        for key in (
            "headline",
            "published_at",
            "observed_at",
            "primary_category",
            "source_name",
            "content_fingerprint",
        ):
            if not item.get(key):
                die(f"items[{idx}].{key} is required")
        fp = item["content_fingerprint"]
        if fp in seen_fingerprints:
            die(f"duplicate content_fingerprint in payload: {fp}")
        seen_fingerprints.add(fp)
        if item.get("raw_evidence_url"):
            die("public staging payload must not contain raw_evidence_url")
        require_https(item.get("canonical_url"), f"items[{idx}].canonical_url")
        if not isinstance(item.get("country_codes", []), list):
            die(f"items[{idx}].country_codes must be an array")
        if not isinstance(item.get("secondary_categories", []), list):
            die(f"items[{idx}].secondary_categories must be an array")
        if not isinstance(item.get("lineage", {}), dict):
            die(f"items[{idx}].lineage must be an object")
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 8:
            die(f"items[{idx}].evidence must contain at most 8 rows")
        for eidx, ev in enumerate(evidence):
            if not isinstance(ev, dict) or ev.get("evidence_type") not in ALLOWED_EVIDENCE:
                die(f"items[{idx}].evidence[{eidx}] invalid")
            if not ev.get("source_name") or not ev.get("source_url"):
                die(f"items[{idx}].evidence[{eidx}] requires source_name/source_url")
            require_https(ev["source_url"], f"items[{idx}].evidence[{eidx}].source_url")


def canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def persist(payload: dict[str, Any], db_url: str) -> tuple[int, int]:
    run = payload["run"]
    items: list[dict[str, Any]] = payload["items"]
    payload_hash = canonical_hash(payload)
    scope = dict(run.get("source_scope", {}))
    scope.update({"payload_sha256": payload_hash, "writer": "github_actions_v1"})

    run_id: int | None = None
    written = 0
    conn = psycopg.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, status
                from market_watch.ingest_runs
                where run_kind = %s
                  and window_start = %s::timestamptz
                  and window_end = %s::timestamptz
                  and source_scope ->> 'payload_sha256' = %s
                order by id desc
                limit 1
                """,
                (run["run_kind"], run["window_start"], run["window_end"], payload_hash),
            )
            existing = cur.fetchone()
            if existing:
                run_id = int(existing[0])
                cur.execute(
                    """
                    update market_watch.ingest_runs
                    set status = 'running', completed_at = null, error_summary = null,
                        requested_by = %s, source_scope = %s, items_seen = %s
                    where id = %s
                    """,
                    (run["requested_by"], Jsonb(scope), len(items), run_id),
                )
            else:
                cur.execute(
                    """
                    insert into market_watch.ingest_runs
                      (run_kind, status, window_start, window_end, requested_by,
                       source_scope, items_seen, items_written)
                    values (%s, 'running', %s::timestamptz, %s::timestamptz, %s, %s, %s, 0)
                    returning id
                    """,
                    (
                        run["run_kind"],
                        run["window_start"],
                        run["window_end"],
                        run["requested_by"],
                        Jsonb(scope),
                        len(items),
                    ),
                )
                run_id = int(cur.fetchone()[0])
        conn.commit()

        for item in items:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into market_watch.content_items
                      (ingest_run_id, content_type, headline, summary, market_read,
                       published_at, observed_at, country_codes, primary_category,
                       secondary_categories, institution, author_or_account, source_name,
                       canonical_url, external_id, content_fingerprint, verification_status,
                       market_impact, is_top_driver, is_last24, is_active, raw_evidence_url, lineage)
                    values
                      (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, null, %s)
                    on conflict (content_fingerprint) do update set
                      ingest_run_id = excluded.ingest_run_id,
                      content_type = excluded.content_type,
                      headline = excluded.headline,
                      summary = excluded.summary,
                      market_read = excluded.market_read,
                      published_at = excluded.published_at,
                      observed_at = excluded.observed_at,
                      country_codes = excluded.country_codes,
                      primary_category = excluded.primary_category,
                      secondary_categories = excluded.secondary_categories,
                      institution = excluded.institution,
                      author_or_account = excluded.author_or_account,
                      source_name = excluded.source_name,
                      canonical_url = excluded.canonical_url,
                      external_id = excluded.external_id,
                      verification_status = excluded.verification_status,
                      market_impact = excluded.market_impact,
                      is_top_driver = excluded.is_top_driver,
                      is_last24 = excluded.is_last24,
                      is_active = excluded.is_active,
                      lineage = excluded.lineage,
                      updated_at = now()
                    returning id
                    """,
                    (
                        run_id,
                        item["content_type"],
                        item["headline"],
                        item.get("summary"),
                        item.get("market_read"),
                        item["published_at"],
                        item["observed_at"],
                        item.get("country_codes", []),
                        item["primary_category"],
                        item.get("secondary_categories", []),
                        item.get("institution"),
                        item.get("author_or_account"),
                        item["source_name"],
                        item.get("canonical_url"),
                        item.get("external_id"),
                        item["content_fingerprint"],
                        item["verification_status"],
                        item["market_impact"],
                        bool(item.get("is_top_driver", False)),
                        bool(item.get("is_last24", False)),
                        bool(item.get("is_active", True)),
                        Jsonb(item.get("lineage", {})),
                    ),
                )
                content_item_id = int(cur.fetchone()[0])

                for ev in item.get("evidence", []):
                    cur.execute(
                        """
                        insert into market_watch.content_evidence
                          (content_item_id, evidence_type, source_name, source_url,
                           published_at, source_account, source_registry_ref,
                           is_primary, notes, captured_at)
                        values (%s, %s, %s, %s, %s::timestamptz, %s, %s, %s, %s, now())
                        on conflict (content_item_id, source_url) do update set
                          evidence_type = excluded.evidence_type,
                          source_name = excluded.source_name,
                          published_at = excluded.published_at,
                          source_account = excluded.source_account,
                          source_registry_ref = excluded.source_registry_ref,
                          is_primary = excluded.is_primary,
                          notes = excluded.notes,
                          captured_at = now()
                        """,
                        (
                            content_item_id,
                            ev["evidence_type"],
                            ev["source_name"],
                            ev["source_url"],
                            ev.get("published_at"),
                            ev.get("source_account"),
                            ev.get("source_registry_ref"),
                            bool(ev.get("is_primary", False)),
                            ev.get("notes"),
                        ),
                    )
            conn.commit()
            written += 1

        with conn.cursor() as cur:
            cur.execute(
                """
                update market_watch.ingest_runs
                set status = 'succeeded', completed_at = now(), items_seen = %s,
                    items_written = %s, error_summary = null
                where id = %s
                """,
                (len(items), written, run_id),
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "select status, items_seen, items_written from market_watch.ingest_runs where id = %s",
                (run_id,),
            )
            status, seen, confirmed = cur.fetchone()
            cur.execute(
                "select count(*) from market_watch.content_items where ingest_run_id = %s",
                (run_id,),
            )
            item_count = int(cur.fetchone()[0])
        if status != "succeeded" or seen != len(items) or confirmed != written or item_count != len(items):
            die(
                f"verification failed for run {run_id}: status={status} seen={seen} "
                f"written={confirmed} item_count={item_count} expected={len(items)}"
            )
        return run_id, written
    except Exception as exc:
        conn.rollback()
        if run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update market_watch.ingest_runs
                        set status = %s, completed_at = now(), items_written = %s,
                            error_summary = %s
                        where id = %s
                        """,
                        ("partial" if written else "failed", written, str(exc)[:2000], run_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PAYLOAD
    if not path.exists():
        die(f"payload not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        die("payload root must be an object")
    validate_payload(payload, path)
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        die("SUPABASE_DB_URL is not configured")
    run_id, written = persist(payload, db_url)
    print(f"Supabase persistence verified: run_id={run_id} items_written={written}")


if __name__ == "__main__":
    main()
