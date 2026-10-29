"""Macro ingestion runner: adapters, calendar, vintage, ledger."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.macro_freshness import values_close
from scripts.macro_ingestion.adapters import load_country_adapter
from scripts.macro_ingestion.calendar import (
    cadence_backstop_due,
    latest_due_release,
    release_due,
    schedule_parseable,
)
from scripts.macro_ingestion.contract import calibration_as_of, load_catalog
from scripts.macro_ingestion.ledger import ledger_row, write_ledger
from scripts.macro_ingestion.retries import retry_call
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.macro_ingestion.semantic_guards import stale_pinned_artifact_error
from scripts.temperature_level import CALIBRATION_PATH
from scripts.macro_ingestion.ea_country_hicp import COUNTRY_HICP_IDS, append_ranked_country_hicp
from scripts.macro_ingestion.vintage import (
    append_observation,
    latest_for_period,
    latest_period_in_store,
    load_store,
    save_store,
    seed_stores,
)
from scripts.macro_ingestion.source_health_summary import build_source_health_summary
from scripts.macro_ingestion.windows import POST_FREEZE_DIR, cutoff_class, write_post_freeze_delta
from scripts.run_state.identity import classify_point_transform

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_COUNTRY_BUDGET_SECONDS = 8 * 60
DEFAULT_RUN_BUDGET_SECONDS = 25 * 60
DEFAULT_ATTEMPTS = 3

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data/macro_ingestion/raw"

PROTECTED_LABOR_IDS = frozenset(
    {
        "US.Labor.payrolls",
        "US.Labor.unemployment",
        "US.Labor.wages",
        "AU.Labor.unemployment",
        "AU.Labor.employment",
    }
)

AU_EARLY_LABOR_IDS = frozenset(
    {
        "AU.Labor.unemployment",
        "AU.Labor.employment",
    }
)


def _utc_iso(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def offline_opener(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    return {
        "ok": False,
        "url": url,
        "http_status": None,
        "body": b"",
        "error": "offline_mode",
    }


# Same public browser identity as scripts.market_state.BROWSER_USER_AGENT.
# The PMI press pages return the public document to this agent and HTTP 403
# to the short bot token.
_PUBLIC_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def live_opener(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    try:
        headers = {
            "User-Agent": _PUBLIC_BROWSER_USER_AGENT,
            "Accept": "application/json,text/xml,text/html,application/pdf,*/*",
        }
        if data is not None:
            headers["Content-Type"] = content_type or "application/json"
        request = Request(
            url,
            data=data,
            headers=headers,
        )
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            return {
                "ok": True,
                "url": url,
                "http_status": getattr(response, "status", None) or response.getcode(),
                "body": body,
                "error": None,
            }
    except HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return {
            "ok": False,
            "url": url,
            "http_status": exc.code,
            "body": body,
            "error": f"HTTP {exc.code}",
        }
    except URLError as exc:
        return {
            "ok": False,
            "url": url,
            "http_status": None,
            "body": b"",
            "error": str(exc.reason) if hasattr(exc, "reason") else str(exc),
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _series_by_country(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in catalog["series"]:
        grouped[row["country"]].append(row)
    return grouped


def _point_release_date(point: dict[str, Any]) -> str | None:
    if "release_date" in point:
        return str(point["release_date"]) if point["release_date"] is not None else None
    if "release_vintage" in point:
        return str(point["release_vintage"]) if point["release_vintage"] is not None else None
    return None


def _confirms_period(
    points: list[dict[str, Any]],
    store: dict[str, Any],
    series_id: str,
    transform: str,
    period: str,
) -> bool:
    """True when this fetch and the store both hold the expected reference period."""
    in_payload = any(str(point.get("period")) == period for point in points)
    in_store = latest_for_period(store, series_id, period, transform) is not None
    return in_payload and in_store


def _allowed_point_transforms(spec: dict[str, Any]) -> frozenset[str]:
    """Spec transform plus any opt-in ``derived_transforms`` the catalog row declares.

    Rows without ``derived_transforms`` accept only the row transform. An
    adapter value outside that set is a mismatch and is not rewritten. A point
    that omits ``transformation`` still uses the row transform.
    """
    base = str(spec.get("transform", ""))
    derived = spec.get("derived_transforms") or []
    return frozenset({base, *(str(item) for item in derived if item is not None)})


def _point_transform(point: dict[str, Any], transform: str, allowed: frozenset[str]) -> str:
    classification = classify_point_transform(point.get("transformation"), transform, allowed)
    if classification == "accepted":
        return str(point.get("transformation"))
    return transform


def _unexpected_point_transforms(
    points: list[dict[str, Any]],
    transform: str,
    allowed: frozenset[str],
) -> list[str]:
    unexpected: list[str] = []
    for point in points:
        if classify_point_transform(point.get("transformation"), transform, allowed) == "mismatch":
            unexpected.append(str(point.get("transformation")))
    return unexpected


def _is_http_404(payload: dict[str, Any]) -> bool:
    if payload.get("http_status") == 404:
        return True
    error = str(payload.get("error") or "")
    return "HTTP 404" in error


def _validate_points(points: list[dict[str, Any]]) -> str | None:
    for point in points:
        if "period" not in point:
            return "malformed_point"
        try:
            value = float(point["value"])
        except (KeyError, TypeError, ValueError):
            return "malformed_point"
        if not math.isfinite(value):
            return "malformed_point"
    return None


def _checked_unchanged_or_stale(
    payload: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], str | None, bool]:
    stale = stale_pinned_artifact_error(payload)
    if stale:
        return "due_missing", [], stale, False
    return "checked_unchanged", [], None, False


def _observation_raw_sha(spec: dict[str, Any], point: dict[str, Any], payload: dict[str, Any]) -> str | None:
    """Digest stored on an observation.

    Country HICP rows must carry the hash of the artifact that produced that
    point. A payload-level digest, or a hash of the reconciled point list,
    would stamp a national print with Eurostat bytes or with a merged payload.
    """
    if spec.get("id") in COUNTRY_HICP_IDS:
        point_sha = point.get("raw_sha256")
        if not point_sha:
            return None
        return str(point_sha)
    return str(payload.get("raw_sha256") or _sha256(json.dumps(point).encode()))


def _classify_points(
    spec: dict[str, Any],
    payload: dict[str, Any],
    store: dict[str, Any],
    when: datetime,
) -> tuple[str, list[dict[str, Any]], str | None, bool]:
    """Return status, changed rows for post-freeze, optional error, and whether to save.

    The last flag is true when a country-HICP fingerprint was corrected without
    a new economic observation, so the store is still written.
    """
    if payload.get("challenge_page"):
        return "license_gap", [], payload.get("error") or "challenge_page", False

    override = payload.get("status")
    if override in {"license_gap", "not_applicable", "source_failed", "due_missing"}:
        return override, [], payload.get("error"), False

    if not payload.get("ok"):
        error = str(payload.get("error") or "")
        # EA flash due-window HTML/403 is a missing primary print, not a license wall.
        # The adapter omits license_gap on purpose so an unpublished listing cannot score.
        flash_due_miss = str(spec.get("id") or "") == "EA.Activity.flash_composite_pmi" or error.startswith(
            "primary_flash_pdf_unavailable"
        )
        if payload.get("http_status") == 403 and not flash_due_miss:
            return "license_gap", [], error or "HTTP 403", False
        if _is_http_404(payload):
            due = latest_due_release(spec, when)
            if due is None:
                transform = str(spec.get("transform", ""))
                series_id = str(spec.get("series_id") or spec["id"])
                latest_period = latest_period_in_store(store, series_id, transform)
                backstop = cadence_backstop_due(
                    spec, latest_period=latest_period, when=when
                )
                if latest_period and backstop:
                    payload["ledger_extra"] = {
                        "publication_state": "due_missing",
                        "cadence_backstop_due": True,
                    }
                    return "due_missing", [], "HTTP 404", False
                payload["ledger_extra"] = {"publication_state": "not_yet_due"}
                return "checked_unchanged", [], None, False
            payload["ledger_extra"] = {"publication_state": "due_missing"}
            return "due_missing", [], "HTTP 404", False
        return "source_failed", [], payload.get("error") or "adapter_not_ok", False

    points = payload.get("points") or []
    malformed = _validate_points(points)
    if malformed:
        return "source_failed", [], malformed, False

    if spec.get("id") in COUNTRY_HICP_IDS and any(not point.get("raw_sha256") for point in points):
        return "source_failed", [], "missing_artifact_sha", False

    changed: list[dict[str, Any]] = []
    had_new = False
    had_revision = False
    had_pending = False
    persist_provenance = False

    transform = str(spec.get("transform", ""))
    series_id = str(spec.get("series_id") or spec["id"])
    payload_vintage = payload.get("vintage")
    payload_vintage_str = str(payload_vintage) if payload_vintage is not None else None
    allowed_transforms = _allowed_point_transforms(spec)
    unexpected = _unexpected_point_transforms(points, transform, allowed_transforms)
    if unexpected:
        ledger_extra: dict[str, Any] = {
            "contract_mismatch": {
                "reason": "unexpected_transformation",
                "concept_id": str(spec["id"]),
                "source_series_id": series_id,
                "expected": sorted(allowed_transforms),
                "actual": sorted(set(unexpected)),
                "persisted": False,
            },
        }
        raw_sha = payload.get("raw_sha256")
        if raw_sha is not None:
            ledger_extra["raw_sha256"] = raw_sha
        payload["ledger_extra"] = ledger_extra
        return "transform_mismatch", [], "unexpected_transformation", False

    for point in points:
        period = str(point["period"])
        value = float(point["value"])
        point_transform = _point_transform(point, transform, allowed_transforms)
        raw_sha = _observation_raw_sha(spec, point, payload)
        if raw_sha is None:
            return "source_failed", [], "missing_artifact_sha", False
        prior_row = latest_for_period(store, series_id, period, point_transform)
        point_vintage = point.get("vintage")
        vintage_for_row = str(point_vintage) if point_vintage is not None else payload_vintage_str
        publisher = point.get("publisher")
        derivation = dict(point.get("derivation") or {})
        if publisher and "publisher" not in derivation:
            derivation["publisher"] = publisher

        if spec["id"] in COUNTRY_HICP_IDS:
            result = append_ranked_country_hicp(
                store,
                series_id=series_id,
                period=period,
                transformation=point_transform,
                value=value,
                raw_sha256=raw_sha,
                retrieved_at=_utc_iso(when),
                release_date=_point_release_date(point),
                vintage=vintage_for_row,
                revision_status=point.get("revision_status"),
                source_url=point.get("source_url"),
                prior=point.get("prior"),
                units=point.get("units"),
                derivation=derivation or None,
            )
            if result.provenance_updated:
                persist_provenance = True
            if result.duplicate:
                continue
            if result.upgraded:
                had_new = True
                had_revision = True
            elif result.appended:
                had_new = True
            else:
                continue
        else:
            result = append_observation(
                store,
                series_id=series_id,
                period=period,
                transformation=point_transform,
                value=value,
                raw_sha256=raw_sha,
                retrieved_at=_utc_iso(when),
                release_date=_point_release_date(point),
                vintage=vintage_for_row,
                revision_status=point.get("revision_status"),
                source_url=point.get("source_url"),
                prior=point.get("prior"),
                units=point.get("units"),
                derivation=derivation or None,
                latest_release_vintage=point.get("latest_release_vintage"),
            )
            if result.duplicate:
                continue
            had_new = True
        changed.append(
            {
                "id": spec["id"],
                "period": period,
                "value": value,
                "transformation": point_transform,
                "revision_status": point.get("revision_status"),
            }
        )
        if spec["id"] not in COUNTRY_HICP_IDS and prior_row and not values_close(
            float(prior_row["value"]), value
        ):
            rev = str(point.get("revision_status") or "")
            if rev in {"flash", "preliminary", "prelim"}:
                had_pending = True
            else:
                had_revision = True
        elif spec["id"] in COUNTRY_HICP_IDS and result.appended and prior_row and not values_close(
            float(prior_row["value"]), value
        ):
            rev = str(point.get("revision_status") or "")
            if rev in {"flash", "preliminary", "prelim"}:
                had_pending = True
            else:
                had_revision = True

    if had_revision:
        return "revision_applied", changed, None, persist_provenance
    if had_pending:
        return "revision_pending", changed, None, persist_provenance
    if had_new:
        return "new_observation", changed, None, persist_provenance

    calendar_unparsed = not schedule_parseable(spec.get("release_rule"))
    backstop = cadence_backstop_due(
        spec,
        latest_period=latest_period_in_store(store, series_id, transform),
        when=when,
    )
    ledger_calendar_extra: dict[str, Any] | None = None
    if calendar_unparsed:
        ledger_calendar_extra = {
            "calendar": "unparsed",
            "cadence_backstop_due": backstop,
        }

    if points and not had_new and not had_revision and not had_pending:
        stale = stale_pinned_artifact_error(payload)
        if stale:
            return "due_missing", [], stale, persist_provenance
        if calendar_unparsed:
            if ledger_calendar_extra:
                payload["ledger_extra"] = {
                    **(payload.get("ledger_extra") or {}),
                    **ledger_calendar_extra,
                }
            return "checked_unchanged", [], None, persist_provenance

    if calendar_unparsed:
        stale = stale_pinned_artifact_error(payload)
        if stale:
            return "due_missing", [], stale, persist_provenance
        return "calendar_unparsed", [], None, persist_provenance

    due = latest_due_release(spec, when)
    if due is None:
        status, unchanged, error, _persist = _checked_unchanged_or_stale(payload)
        return status, unchanged, error, persist_provenance

    fixture = (spec.get("known_fixture") or {}).get("period")
    fixture_period = str(fixture) if fixture else None
    if fixture_period and not _confirms_period(points, store, series_id, transform, fixture_period):
        return "due_missing", [], None, persist_provenance

    bound = due.get("period")
    if bound:
        if _confirms_period(points, store, series_id, transform, str(bound)):
            status, unchanged, error, _persist = _checked_unchanged_or_stale(payload)
            return status, unchanged, error, persist_provenance
        return "due_missing", [], None, persist_provenance

    if fixture_period and _confirms_period(points, store, series_id, transform, fixture_period):
        status, unchanged, error, _persist = _checked_unchanged_or_stale(payload)
        return status, unchanged, error, persist_provenance

    return "calendar_unparsed", [], None, persist_provenance


def _budget_exhausted(
    clock: Callable[[], float],
    run_start: float,
    country_start: float,
    run_budget_seconds: float,
    country_budget_seconds: float,
) -> bool:
    now = clock()
    return (now - run_start) > run_budget_seconds or (now - country_start) > country_budget_seconds


def _deferred_row(
    spec: dict[str, Any],
    *,
    checked_at: str,
    calibration_as_of: str,
    cutoff_class: str,
    scheduler_kind: str | None = None,
    scheduler_reason: str | None = None,
) -> dict[str, Any]:
    row = ledger_row(
        series_id=spec["id"],
        status="source_failed",
        checked_at=checked_at,
        observation_vintage=None,
        calibration_as_of=calibration_as_of,
        cutoff_class=cutoff_class,
        error="budget_deferred",
    )
    if scheduler_kind and scheduler_reason:
        _append_scheduler_event(row, kind=scheduler_kind, reason=scheduler_reason)
    return row


def _protected_due_labor(spec: dict[str, Any], when: datetime) -> bool:
    if str(spec.get("id") or "") not in PROTECTED_LABOR_IDS:
        return False
    return latest_due_release(spec, when) is not None


def _prior_budget_deferred_ids(prior_rows: list[dict[str, Any]] | None) -> frozenset[str]:
    if not prior_rows:
        return frozenset()
    return frozenset(
        str(row["series_id"])
        for row in prior_rows
        if row.get("error") == "budget_deferred"
    )


def _series_tier(spec: dict[str, Any], when: datetime, prior_deferred: frozenset[str]) -> int:
    if _protected_due_labor(spec, when):
        return 0
    if str(spec.get("id") or "") in prior_deferred:
        return 1
    if release_due(spec, when):
        return 2
    if str(spec.get("role") or "") == "scored":
        return 3
    return 4


def _series_lane(spec: dict[str, Any], when: datetime) -> int:
    """Legacy lane helper for admission/retry reason strings."""
    if _protected_due_labor(spec, when):
        return 0
    if str(spec.get("role") or "") == "scored":
        return 1
    return 2


def _spec_host(spec: dict[str, Any]) -> str:
    for key in ("endpoint", "fallback_endpoint"):
        url = spec.get(key)
        if url:
            parsed = urlparse(str(url))
            if parsed.netloc:
                return parsed.netloc.lower()
    publisher = spec.get("publisher")
    if publisher:
        return str(publisher).lower()
    return "unknown"


def _is_transport_failure(*, error: str | None = None, exc: BaseException | None = None) -> bool:
    if exc is not None:
        if isinstance(exc, (TimeoutError, URLError, ConnectionError, OSError)):
            return True
        text = str(exc)
        if "timed out" in text.lower():
            return True
    if error:
        lowered = error.lower()
        if "timed out" in lowered:
            return True
        if "urlerror" in lowered or "connection" in lowered:
            return True
    return False


def _round_robin_host_order(
    pending: list[dict[str, Any]],
    *,
    when: datetime,
    prior_deferred: frozenset[str],
) -> list[dict[str, Any]]:
    by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for spec in pending:
        by_host[_spec_host(spec)].append(spec)
    for host in by_host:
        by_host[host].sort(
            key=lambda item: (_series_tier(item, when, prior_deferred), str(item.get("id") or ""))
        )
    hosts = sorted(by_host.keys())
    queues = {host: list(by_host[host]) for host in hosts}
    ordered: list[dict[str, Any]] = []
    while any(queues[host] for host in hosts):
        for host in hosts:
            if queues[host]:
                ordered.append(queues[host].pop(0))
    return ordered


def _host_deferred_row(
    spec: dict[str, Any],
    *,
    checked_at: str,
    calibration_as_of: str,
    cutoff_class: str,
) -> dict[str, Any]:
    row = ledger_row(
        series_id=spec["id"],
        status="source_failed",
        checked_at=checked_at,
        observation_vintage=None,
        calibration_as_of=calibration_as_of,
        cutoff_class=cutoff_class,
        error="host_deferred",
    )
    _append_scheduler_event(row, kind="skipped_admission", reason="host_deferred")
    return row


def _retryable_row(row: dict[str, Any]) -> bool:
    if row.get("status") != "source_failed":
        return False
    error = str(row.get("error") or "")
    if error in {"budget_deferred", "host_deferred"}:
        return False
    return True


def _append_scheduler_event(row: dict[str, Any], *, kind: str, reason: str) -> None:
    events = list(row.get("scheduler_events") or [])
    events.append({"kind": kind, "reason": reason, "series_id": row.get("series_id")})
    row["scheduler_events"] = events


def _deferred_admission_reason(
    spec: dict[str, Any],
    *,
    when: datetime,
    protected_due_total: int,
    protected_admitted: int,
) -> str:
    if _protected_due_labor(spec, when):
        return "protected_budget_exhausted"
    if protected_admitted < protected_due_total:
        return "starved_by_critical_reservation"
    return "budget_exhausted"


def _skipped_retry_reason(
    spec: dict[str, Any],
    *,
    when: datetime,
    protected_failures: int,
    protected_retries_admitted: int,
) -> str:
    if _protected_due_labor(spec, when):
        return "protected_budget_exhausted"
    if protected_retries_admitted < protected_failures:
        return "starved_by_critical_reservation"
    return "budget_exhausted"


def _history_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    prior = dict(row)
    prior.pop("attempt_history", None)
    return prior


def _row_with_attempt_history(
    new_row: dict[str, Any],
    prior_row: dict[str, Any],
) -> dict[str, Any]:
    history = list(prior_row.get("attempt_history") or [])
    history.append(_history_snapshot(prior_row))
    merged = dict(new_row)
    merged["attempt_history"] = history
    return merged


def _fetch_once(
    spec: dict[str, Any],
    *,
    fetch_fn: Callable[..., dict[str, Any]],
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout_seconds: float,
    rows: list[dict[str, Any]],
    rows_lock: threading.Lock,
    checked_at: str,
    cal_as_of: str,
    cutoff: str,
    mode: str,
    raw_dir: Path | None,
    country: str,
    store: dict[str, Any],
    store_lock: threading.Lock,
    obs_dir: Path,
    post_freeze_changes: list[dict[str, Any]],
    replace_index: int | None = None,
    extra_attempts: int = 0,
) -> int:
    """Fetch one series. Retries stay inside this series and cannot skip siblings."""

    def _fetch() -> dict[str, Any]:
        return fetch_fn(spec, opener=opener, now=now, timeout=timeout_seconds)

    call_attempts = extra_attempts if replace_index is not None else 1
    if call_attempts < 1:
        return replace_index if replace_index is not None else len(rows) - 1
    try:
        payload = retry_call(_fetch, attempts=call_attempts)
    except Exception as exc:  # noqa: BLE001
        row = ledger_row(
            series_id=spec["id"],
            status="source_failed",
            checked_at=checked_at,
            observation_vintage=None,
            calibration_as_of=cal_as_of,
            cutoff_class=cutoff,
            error=str(exc),
        )
        with rows_lock:
            if replace_index is None:
                rows.append(row)
                return len(rows) - 1
            rows[replace_index] = _row_with_attempt_history(row, rows[replace_index])
            return replace_index

    if mode == "live" and payload.get("ok") and raw_dir is not None:
        body = payload.get("body") or b""
        if body:
            sid = spec.get("series_id") or "unknown"
            digest = _sha256(body)[:12]
            stamp = checked_at.replace(":", "").replace("-", "")
            out = raw_dir / country.lower() / str(sid) / f"{stamp}-{digest}"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)

    with store_lock:
        status, changed, error, persist_provenance = _classify_points(spec, payload, store, now)
        vintage = payload.get("vintage")
        ledger_extra = payload.get("ledger_extra")
        row = ledger_row(
            series_id=spec["id"],
            status=status,
            checked_at=checked_at,
            observation_vintage=str(vintage) if vintage is not None else None,
            calibration_as_of=cal_as_of,
            cutoff_class=cutoff,
            error=error,
            extra=ledger_extra if isinstance(ledger_extra, dict) else None,
        )
        if changed or persist_provenance:
            save_store(store, obs_dir)
        if changed:
            post_freeze_changes.extend(changed)
        with rows_lock:
            if replace_index is None:
                rows.append(row)
                return len(rows) - 1
            rows[replace_index] = _row_with_attempt_history(row, rows[replace_index])
            return replace_index


def _ingest_country_pending(
    pending: list[dict[str, Any]],
    *,
    fetch_fn: Callable[..., dict[str, Any]],
    opener: Callable[..., dict[str, Any]],
    when: datetime,
    timeout_seconds: float,
    rows: list[dict[str, Any]],
    checked_at: str,
    cal_as_of: str,
    cutoff: str,
    mode: str,
    raw_dir: Path | None,
    country: str,
    obs_dir: Path,
    post_freeze_changes: list[dict[str, Any]],
    clock: Callable[[], float],
    run_start: float,
    country_start: float,
    run_budget_seconds: float,
    country_budget_seconds: float,
    attempts: int,
    prior_rows: list[dict[str, Any]] | None = None,
    group_parallelism: int = 4,
    per_host_limit: int = 1,
    host_failure_limit: int = 2,
) -> set[str]:
    """Fetch pending series for one country; return ids that received a ledger row."""
    admitted: set[str] = set()
    prior_deferred = _prior_budget_deferred_ids(prior_rows)
    ordered = _round_robin_host_order(pending, when=when, prior_deferred=prior_deferred)
    multiple_hosts = len({_spec_host(spec) for spec in ordered}) > 1
    protected_due_total = sum(1 for spec in ordered if _protected_due_labor(spec, when))
    protected_admitted = 0

    store = load_store(country, obs_dir)
    store_lock = threading.Lock()
    rows_lock = threading.Lock()
    budget_lock = threading.Lock()
    host_failures: dict[str, int] = defaultdict(int)
    host_deferred: set[str] = set()
    host_semaphores: dict[str, threading.Semaphore] = {}
    host_sem_lock = threading.Lock()
    failed_for_retry: list[tuple[dict[str, Any], int]] = []

    def _host_sem(host: str) -> threading.Semaphore:
        with host_sem_lock:
            if host not in host_semaphores:
                host_semaphores[host] = threading.Semaphore(max(1, per_host_limit))
            return host_semaphores[host]

    def _record_transport_failure(host: str) -> None:
        host_failures[host] += 1
        if host_failures[host] >= host_failure_limit:
            host_deferred.add(host)

    def _fetch_and_classify(
        spec: dict[str, Any],
        *,
        replace_index: int | None = None,
        extra_attempts: int = 0,
    ) -> int:
        host = _spec_host(spec)
        sem = _host_sem(host)
        sem.acquire()
        try:
            row_index = _fetch_once(
                spec,
                fetch_fn=fetch_fn,
                opener=opener,
                now=when,
                timeout_seconds=timeout_seconds,
                rows=rows,
                rows_lock=rows_lock,
                checked_at=checked_at,
                cal_as_of=cal_as_of,
                cutoff=cutoff,
                mode=mode,
                raw_dir=raw_dir,
                country=country,
                store=store,
                store_lock=store_lock,
                obs_dir=obs_dir,
                post_freeze_changes=post_freeze_changes,
                replace_index=replace_index,
                extra_attempts=extra_attempts,
            )
        finally:
            sem.release()
        with rows_lock:
            row = rows[row_index]
        if row.get("status") == "source_failed" and _is_transport_failure(
            error=str(row.get("error") or "")
        ):
            with budget_lock:
                _record_transport_failure(host)
        return row_index

    def _run_pass(work: list[tuple[dict[str, Any], int | None, int]]) -> None:
        nonlocal protected_admitted
        if not work:
            return
        max_workers = max(1, min(group_parallelism, len(work)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            queue = list(work)
            in_flight: dict[Future[int], tuple[dict[str, Any], int | None, bool]] = {}

            def _drain_done(done: set[Future[int]]) -> None:
                nonlocal protected_admitted
                for fut in done:
                    spec, replace_index, is_initial = in_flight.pop(fut)
                    row_index = fut.result()
                    admitted.add(str(spec["id"]))
                    with rows_lock:
                        row = rows[row_index]
                    if is_initial and _protected_due_labor(spec, when):
                        protected_admitted += 1
                    if is_initial and attempts > 1 and _retryable_row(row):
                        failed_for_retry.append((spec, row_index))

            while queue or in_flight:
                while queue and len(in_flight) < max_workers:
                    spec, replace_index, extra = queue[0]
                    host = _spec_host(spec)
                    if host in host_deferred and multiple_hosts:
                        queue.pop(0)
                        if replace_index is None:
                            with rows_lock:
                                rows.append(
                                    _host_deferred_row(
                                        spec,
                                        checked_at=checked_at,
                                        calibration_as_of=cal_as_of,
                                        cutoff_class=cutoff,
                                    )
                                )
                        continue
                    if replace_index is None:
                        with budget_lock:
                            if _budget_exhausted(
                                clock,
                                run_start,
                                country_start,
                                run_budget_seconds,
                                country_budget_seconds,
                            ):
                                queue.pop(0)
                                with rows_lock:
                                    rows.append(
                                        _deferred_row(
                                            spec,
                                            checked_at=checked_at,
                                            calibration_as_of=cal_as_of,
                                            cutoff_class=cutoff,
                                            scheduler_kind="skipped_admission",
                                            scheduler_reason=_deferred_admission_reason(
                                                spec,
                                                when=when,
                                                protected_due_total=protected_due_total,
                                                protected_admitted=protected_admitted,
                                            ),
                                        )
                                    )
                                continue
                    queue.pop(0)
                    is_initial = replace_index is None
                    fut = pool.submit(
                        _fetch_and_classify,
                        spec,
                        replace_index=replace_index,
                        extra_attempts=extra,
                    )
                    in_flight[fut] = (spec, replace_index, is_initial)
                    if len(in_flight) >= max_workers:
                        break

                if not in_flight:
                    break
                done, _ = wait(set(in_flight.keys()), return_when=FIRST_COMPLETED)
                _drain_done(done)

    failed_for_retry.clear()
    _run_pass([(spec, None, 1) for spec in ordered])

    protected_failures = sum(1 for spec, _ in failed_for_retry if _protected_due_labor(spec, when))
    protected_retries_admitted = 0
    failed_for_retry.sort(
        key=lambda item: (_series_tier(item[0], when, prior_deferred), str(item[0].get("id") or ""))
    )

    retry_work: list[tuple[dict[str, Any], int | None, int]] = []
    for spec, row_index in failed_for_retry:
        with budget_lock:
            if _budget_exhausted(
                clock,
                run_start,
                country_start,
                run_budget_seconds,
                country_budget_seconds,
            ):
                with rows_lock:
                    _append_scheduler_event(
                        rows[row_index],
                        kind="skipped_retry",
                        reason=_skipped_retry_reason(
                            spec,
                            when=when,
                            protected_failures=protected_failures,
                            protected_retries_admitted=protected_retries_admitted,
                        ),
                    )
                continue
        retry_work.append((spec, row_index, attempts - 1))
        if _protected_due_labor(spec, when):
            protected_retries_admitted += 1

    if retry_work:
        failed_for_retry.clear()
        _run_pass(retry_work)

    return admitted


def run_ingestion(
    *,
    mode: str = "offline",
    countries: list[str] | None = None,
    now: datetime | None = None,
    opener: Callable[..., dict[str, Any]] | None = None,
    catalog: dict[str, Any] | None = None,
    observations_dir: Path | None = None,
    health_dir: Path | None = None,
    raw_dir: Path | None = None,
    country_budget_seconds: float = DEFAULT_COUNTRY_BUDGET_SECONDS,
    run_budget_seconds: float = DEFAULT_RUN_BUDGET_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] | None = None,
    run_id: str | None = None,
    persist_canonical: bool = False,
    only_series_ids: set[str] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    write_health: bool = True,
    seed_observations_from: Path | None = None,
    prior_rows: list[dict[str, Any]] | None = None,
    group_parallelism: int = 4,
    per_host_limit: int = 1,
    host_failure_limit: int = 2,
) -> dict[str, Any]:
    catalog = catalog or load_catalog()
    when = now or datetime.now(timezone.utc)
    checked_at = _utc_iso(when)
    cal_as_of = calibration_as_of(catalog)
    cutoff = cutoff_class(when)

    if opener is None:
        opener = offline_opener if mode == "offline" else live_opener

    obs_dir = observations_dir or (ROOT / "data/macro_ingestion/observations")
    if seed_observations_from is not None:
        seed_stores(obs_dir, seed_observations_from)
    grouped = _series_by_country(catalog)
    target_countries = [c.upper() for c in (countries or list(grouped.keys()))]

    rows: list[dict[str, Any]] = []
    post_freeze_changes: list[dict[str, Any]] = []

    import time as _time

    clock = monotonic or _time.monotonic
    run_start = clock()
    early_admitted_ids: set[str] = set()

    if "AU" in target_countries:
        au_fetch_fn = load_country_adapter("AU")
        if au_fetch_fn is not None:
            au_series = grouped.get("AU", [])
            au_early_pending = [
                spec
                for spec in au_series
                if str(spec.get("id") or "") in AU_EARLY_LABOR_IDS
                and latest_due_release(spec, when) is not None
                and (only_series_ids is None or str(spec["id"]) in only_series_ids)
            ]
            if au_early_pending:
                au_early_start = clock()
                early_admitted_ids = _ingest_country_pending(
                    au_early_pending,
                    fetch_fn=au_fetch_fn,
                    opener=opener,
                    when=when,
                    timeout_seconds=timeout_seconds,
                    rows=rows,
                    checked_at=checked_at,
                    cal_as_of=cal_as_of,
                    cutoff=cutoff,
                    mode=mode,
                    raw_dir=raw_dir,
                    country="AU",
                    obs_dir=obs_dir,
                    post_freeze_changes=post_freeze_changes,
                    clock=clock,
                    run_start=run_start,
                    country_start=au_early_start,
                    run_budget_seconds=run_budget_seconds,
                    country_budget_seconds=country_budget_seconds,
                    attempts=attempts,
                    prior_rows=prior_rows,
                    group_parallelism=group_parallelism,
                    per_host_limit=per_host_limit,
                    host_failure_limit=host_failure_limit,
                )

    ingest_kwargs = {
        "prior_rows": prior_rows,
        "group_parallelism": group_parallelism,
        "per_host_limit": per_host_limit,
        "host_failure_limit": host_failure_limit,
    }

    for country in target_countries:
        country_start = clock()
        # Scored inputs get breadth before context-only enrichment so one slow
        # source cannot consume the country budget before the trade gate is usable.
        series_list = sorted(
            grouped.get(country, []),
            key=lambda spec: (
                _series_lane(spec, when),
                str(spec.get("id") or ""),
            ),
        )
        fetch_fn = load_country_adapter(country)
        if fetch_fn is None:
            for spec in series_list:
                rows.append(
                    ledger_row(
                        series_id=spec["id"],
                        status="incomplete_country",
                        checked_at=checked_at,
                        observation_vintage=None,
                        calibration_as_of=cal_as_of,
                        cutoff_class=cutoff,
                        error="adapter_module_missing",
                    )
                )
            continue

        pending = [
            spec
            for spec in series_list
            if only_series_ids is None or str(spec["id"]) in only_series_ids
            if str(spec.get("id") or "") not in early_admitted_ids
        ]
        if not pending:
            continue
        _ingest_country_pending(
            pending,
            fetch_fn=fetch_fn,
            opener=opener,
            when=when,
            timeout_seconds=timeout_seconds,
            rows=rows,
            checked_at=checked_at,
            cal_as_of=cal_as_of,
            cutoff=cutoff,
            mode=mode,
            raw_dir=raw_dir,
            country=country,
            obs_dir=obs_dir,
            post_freeze_changes=post_freeze_changes,
            clock=clock,
            run_start=run_start,
            country_start=country_start,
            run_budget_seconds=run_budget_seconds,
            country_budget_seconds=country_budget_seconds,
            attempts=attempts,
            **ingest_kwargs,
        )

    if write_health:
        write_ledger(rows, health_dir=health_dir or (ROOT / "data/macro_ingestion/health"), run_id=run_id)

    if persist_canonical:
        recompute_scores_after_observation(
            persist_history=True,
            persist_scores=True,
            observations_dir=obs_dir,
            checked_at=checked_at,
            calibration_path=CALIBRATION_PATH,
        )

    post_freeze_path = None
    if cutoff == "post_freeze" and post_freeze_changes:
        # Tests pass a private observations_dir. Keep their deltas beside it
        # so a unit run cannot append immutable files under the repo tree.
        freeze_base = None
        if observations_dir is not None:
            freeze_base = Path(observations_dir).parent / "post_freeze"
        post_freeze_path = write_post_freeze_delta(
            when=when,
            changed_series=post_freeze_changes,
            run_id=run_id,
            base_dir=freeze_base or POST_FREEZE_DIR,
        )

    return {
        "mode": mode,
        "checked_at": checked_at,
        "calibration_as_of": cal_as_of,
        "cutoff_class": cutoff,
        "rows": rows,
        "post_freeze_path": str(post_freeze_path) if post_freeze_path else None,
        "source_health_summary": build_source_health_summary(rows),
    }
