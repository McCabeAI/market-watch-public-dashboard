"""Macro ingestion runner: adapters, calendar, vintage, ledger."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.macro_freshness import values_close
from scripts.macro_ingestion.adapters import load_country_adapter
from scripts.macro_ingestion.calendar import latest_due_release, schedule_parseable
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
    load_store,
    save_store,
)
from scripts.macro_ingestion.windows import POST_FREEZE_DIR, cutoff_class, write_post_freeze_delta

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_COUNTRY_BUDGET_SECONDS = 8 * 60
DEFAULT_RUN_BUDGET_SECONDS = 25 * 60
DEFAULT_ATTEMPTS = 3

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data/macro_ingestion/raw"


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

    Rows without ``derived_transforms`` keep the legacy behaviour: every point
    is stored under the row's single ``transform`` regardless of what the
    adapter wrote on the point.
    """
    base = str(spec.get("transform", ""))
    derived = spec.get("derived_transforms") or []
    return frozenset({base, *(str(item) for item in derived if item is not None)})


def _point_transform(point: dict[str, Any], transform: str, allowed: frozenset[str]) -> str:
    candidate = point.get("transformation")
    if candidate is None:
        return transform
    candidate = str(candidate)
    return candidate if candidate in allowed else transform


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
    if override in {"license_gap", "not_applicable", "source_failed"}:
        return override, [], payload.get("error"), False

    if not payload.get("ok"):
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

    if not schedule_parseable(spec.get("release_rule")):
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
) -> dict[str, Any]:
    return ledger_row(
        series_id=spec["id"],
        status="source_failed",
        checked_at=checked_at,
        observation_vintage=None,
        calibration_as_of=calibration_as_of,
        cutoff_class=cutoff_class,
        error="budget_deferred",
    )


def _fetch_once(
    spec: dict[str, Any],
    *,
    fetch_fn: Callable[..., dict[str, Any]],
    opener: Callable[..., dict[str, Any]],
    now: datetime,
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
    replace_index: int | None = None,
    extra_attempts: int = 0,
) -> int:
    """Fetch one series. Retries stay inside this series and cannot skip siblings."""
    store = load_store(country, obs_dir)

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
        if replace_index is None:
            rows.append(row)
            return len(rows) - 1
        rows[replace_index] = row
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

    status, changed, error, persist_provenance = _classify_points(spec, payload, store, now)
    vintage = payload.get("vintage")
    row = ledger_row(
        series_id=spec["id"],
        status=status,
        checked_at=checked_at,
        observation_vintage=str(vintage) if vintage is not None else None,
        calibration_as_of=cal_as_of,
        cutoff_class=cutoff,
        error=error,
    )
    if changed or persist_provenance:
        save_store(store, obs_dir)
    if changed:
        post_freeze_changes.extend(changed)
    if replace_index is None:
        rows.append(row)
        return len(rows) - 1
    rows[replace_index] = row
    return replace_index


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
) -> dict[str, Any]:
    catalog = catalog or load_catalog()
    when = now or datetime.now(timezone.utc)
    checked_at = _utc_iso(when)
    cal_as_of = calibration_as_of(catalog)
    cutoff = cutoff_class(when)

    if opener is None:
        opener = offline_opener if mode == "offline" else live_opener

    obs_dir = observations_dir or (ROOT / "data/macro_ingestion/observations")
    grouped = _series_by_country(catalog)
    target_countries = [c.upper() for c in (countries or list(grouped.keys()))]

    rows: list[dict[str, Any]] = []
    post_freeze_changes: list[dict[str, Any]] = []

    import time as _time

    clock = monotonic or _time.monotonic
    run_start = clock()

    for country in target_countries:
        country_start = clock()
        # Scored inputs get breadth before context-only enrichment so one slow
        # source cannot consume the country budget before the trade gate is usable.
        series_list = sorted(
            grouped.get(country, []),
            key=lambda spec: (
                0 if str(spec.get("role") or "") == "scored" else 1,
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
        ]
        # One attempt per series before any retry. A slow FRED read must not
        # spend the country budget and stamp untouched series budget_deferred.
        failed_for_retry: list[tuple[dict[str, Any], int]] = []
        for spec in pending:
            if _budget_exhausted(clock, run_start, country_start, run_budget_seconds, country_budget_seconds):
                rows.append(
                    _deferred_row(
                        spec,
                        checked_at=checked_at,
                        calibration_as_of=cal_as_of,
                        cutoff_class=cutoff,
                    )
                )
                continue

            row_index = _fetch_once(
                spec,
                fetch_fn=fetch_fn,
                opener=opener,
                now=when,
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
            )
            row = rows[row_index]
            if attempts > 1 and row.get("status") == "source_failed" and row.get("error") != "budget_deferred":
                failed_for_retry.append((spec, row_index))

        for spec, row_index in failed_for_retry:
            if _budget_exhausted(clock, run_start, country_start, run_budget_seconds, country_budget_seconds):
                # Keep the first truthful failure. Do not relabel an attempted read.
                continue
            _fetch_once(
                spec,
                fetch_fn=fetch_fn,
                opener=opener,
                now=when,
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
                replace_index=row_index,
                extra_attempts=attempts - 1,
            )

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
    }
