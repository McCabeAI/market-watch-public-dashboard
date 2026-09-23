"""Macro ingestion runner: adapters, calendar, vintage, ledger."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from scripts.macro_freshness import values_close
from scripts.macro_ingestion.adapters import load_country_adapter
from scripts.macro_ingestion.calendar import release_due, schedule_parseable
from scripts.macro_ingestion.contract import calibration_as_of, load_catalog
from scripts.macro_ingestion.ledger import ledger_row, write_ledger
from scripts.macro_ingestion.retries import retry_call
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.macro_ingestion.vintage import (
    append_observation,
    latest_for_period,
    load_store,
    save_store,
)
from scripts.macro_ingestion.windows import cutoff_class, write_post_freeze_delta

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_COUNTRY_BUDGET_SECONDS = 8 * 60
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


def live_opener(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "market-watch-macro-ingestion/1.0"})
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            return {
                "ok": True,
                "url": url,
                "http_status": getattr(response, "status", None) or response.getcode(),
                "body": body,
                "error": None,
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


def _classify_points(
    spec: dict[str, Any],
    payload: dict[str, Any],
    store: dict[str, Any],
    when: datetime,
) -> tuple[str, list[dict[str, Any]], str | None]:
    """Return status, changed rows for post-freeze, optional error."""
    if payload.get("challenge_page"):
        return "license_gap", [], payload.get("error") or "challenge_page"

    override = payload.get("status")
    if override in {"license_gap", "not_applicable", "source_failed"}:
        return override, [], payload.get("error")

    if not payload.get("ok"):
        return "source_failed", [], payload.get("error") or "adapter_not_ok"

    points = payload.get("points") or []
    changed: list[dict[str, Any]] = []
    had_new = False
    had_revision = False
    had_pending = False

    transform = str(spec.get("transform", ""))
    series_id = str(spec.get("series_id") or spec["id"])

    for point in points:
        period = str(point["period"])
        value = float(point["value"])
        raw_sha = str(payload.get("raw_sha256") or _sha256(json.dumps(point).encode()))
        prior_row = latest_for_period(store, series_id, period, transform)
        result = append_observation(
            store,
            series_id=series_id,
            period=period,
            transformation=transform,
            value=value,
            raw_sha256=raw_sha,
            retrieved_at=_utc_iso(when),
            revision_status=point.get("revision_status"),
            source_url=point.get("source_url"),
            prior=point.get("prior"),
        )
        if result.duplicate:
            continue
        had_new = True
        changed.append(
            {
                "id": spec["id"],
                "period": period,
                "value": value,
                "revision_status": point.get("revision_status"),
            }
        )
        if prior_row and not values_close(float(prior_row["value"]), value):
            rev = str(point.get("revision_status") or "")
            if rev in {"flash", "preliminary", "prelim"}:
                had_pending = True
            else:
                had_revision = True

    if had_revision:
        return "revision_applied", changed, None
    if had_pending:
        return "revision_pending", changed, None
    if had_new:
        return "new_observation", changed, None

    if not schedule_parseable(spec.get("release_rule")):
        return "calendar_unparsed", [], None

    if release_due(spec, when):
        expected_period = (spec.get("known_fixture") or {}).get("period")
        if expected_period and not latest_for_period(store, series_id, expected_period, transform):
            return "release_due_missing", [], None
        if points:
            return "checked_success_no_new_release", [], None
        return "release_due_missing", [], "release_window_open_no_primary_point"

    return "checked_success_no_new_release", [], None


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
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] | None = None,
    run_id: str | None = None,
    persist_scores: bool = False,
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
    scored_append = False

    import time as _time

    clock = monotonic or _time.monotonic

    for country in target_countries:
        country_start = clock()
        series_list = grouped.get(country, [])
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

        for spec in series_list:
            if clock() - country_start > country_budget_seconds:
                rows.append(
                    ledger_row(
                        series_id=spec["id"],
                        status="source_failed",
                        checked_at=checked_at,
                        observation_vintage=None,
                        calibration_as_of=cal_as_of,
                        cutoff_class=cutoff,
                        error="budget_deferred",
                    )
                )
                continue

            store = load_store(country, obs_dir)

            def _fetch() -> dict[str, Any]:
                return fetch_fn(spec, opener=opener, now=when, timeout=timeout_seconds)

            try:
                payload = retry_call(_fetch, attempts=DEFAULT_ATTEMPTS)
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    ledger_row(
                        series_id=spec["id"],
                        status="source_failed",
                        checked_at=checked_at,
                        observation_vintage=None,
                        calibration_as_of=cal_as_of,
                        cutoff_class=cutoff,
                        error=str(exc),
                    )
                )
                continue

            if mode == "live" and payload.get("ok") and raw_dir is not None:
                body = payload.get("body") or b""
                if body:
                    sid = spec.get("series_id") or "unknown"
                    digest = _sha256(body)[:12]
                    stamp = checked_at.replace(":", "").replace("-", "")
                    out = raw_dir / country.lower() / str(sid) / f"{stamp}-{digest}"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(body)

            status, changed, error = _classify_points(spec, payload, store, when)
            vintage = payload.get("vintage")
            extra: dict[str, Any] = {}
            if status in {"new_observation", "revision_applied"} and spec.get("role") == "scored":
                scored_append = True

            rows.append(
                ledger_row(
                    series_id=spec["id"],
                    status=status,
                    checked_at=checked_at,
                    observation_vintage=str(vintage) if vintage is not None else None,
                    calibration_as_of=cal_as_of,
                    cutoff_class=cutoff,
                    error=error,
                    extra=extra,
                )
            )

            if changed:
                save_store(store, obs_dir)
                post_freeze_changes.extend(changed)

    if scored_append:
        recompute_scores_after_observation(persist_scores=persist_scores, persist_history=False)

    write_ledger(rows, health_dir=health_dir or (ROOT / "data/macro_ingestion/health"), run_id=run_id)

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
