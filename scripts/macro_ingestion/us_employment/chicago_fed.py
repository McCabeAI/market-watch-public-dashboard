"""Ingest published Chicago Fed Labor Market Indicators. No private-model rebuild."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.cache import cache_get, cache_put, is_challenge_page, open_url
from scripts.macro_ingestion.us_employment.contract import (
    CHICAGO_PORTAL_URL,
    CHICAGO_PROBABILITY_BINS,
    CHICAGO_SERIES,
)

_HISTORY_LIMIT = 18
_FINAL_NOWCAST = "CFLMIFORECASTFIN50"
_ADVANCE_NOWCAST = "CFLMIFORECASTADV50"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _period(stamp: str) -> str | None:
    text = str(stamp).strip()
    if len(text) < 7:
        return None
    return text[:7]


def _parse_release_date(text: str) -> str | None:
    raw = " ".join(text.strip().split())
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _points_from_pairs(pairs: list[tuple[str, float]]) -> list[dict[str, Any]]:
    ordered = sorted(pairs, key=lambda item: item[0])
    tail = ordered[-_HISTORY_LIMIT:]
    points: list[dict[str, Any]] = []
    previous: float | None = None
    for period, value in tail:
        point: dict[str, Any] = {"period": period, "value": value}
        if previous is not None:
            point["prior"] = previous
        points.append(point)
        previous = value
    return points


def load_chicago_bundle(
    opener: Callable[..., Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    cached = cache_get(opener, "chicago_fed_lmi")
    if cached is not None:
        return cached

    portal = open_url(opener, CHICAGO_PORTAL_URL, timeout=timeout)
    body: bytes = portal.get("body") or b""
    if not portal.get("ok"):
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": portal.get("error") or "chicago_fed_portal_failed",
            "http_status": portal.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "chicago_fed_lmi", bundle)
    if is_challenge_page(body):
        bundle = {
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "chicago_fed_challenge_page",
            "http_status": portal.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "chicago_fed_lmi", bundle)
    try:
        portal_doc = json.loads(body.decode("utf-8"))
        data = portal_doc.get("data") or {}
        json_url = str(data["chiLaborMarketIndicatorsJson"])
        release_url = str(data.get("releaseDateTxt") or "")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": f"chicago_fed_portal_unparsed:{exc.__class__.__name__}",
            "http_status": portal.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "chicago_fed_lmi", bundle)

    payload = open_url(opener, json_url, timeout=timeout)
    raw: bytes = payload.get("body") or b""
    if not payload.get("ok") or is_challenge_page(raw):
        bundle = {
            "ok": False,
            "status": "license_gap" if is_challenge_page(raw) else "source_failed",
            "challenge_page": is_challenge_page(raw),
            "error": payload.get("error") or "chicago_fed_json_failed",
            "http_status": payload.get("http_status"),
            "body": raw,
        }
        return cache_put(opener, "chicago_fed_lmi", bundle)
    try:
        document = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": "chicago_fed_json_unparsed",
            "http_status": payload.get("http_status"),
            "body": raw,
        }
        return cache_put(opener, "chicago_fed_lmi", bundle)

    release_date = None
    if release_url:
        release = open_url(opener, release_url, timeout=timeout)
        if release.get("ok") and release.get("body"):
            release_date = _parse_release_date(release["body"].decode("utf-8", errors="replace"))

    series_map: dict[str, list[tuple[str, float]]] = {}
    for series in document.get("series") or []:
        source_id = str(series.get("source_id") or "")
        pairs: list[tuple[str, float]] = []
        for obs in series.get("observations") or []:
            if not isinstance(obs, (list, tuple)) or len(obs) < 2:
                continue
            period = _period(str(obs[0]))
            if period is None or obs[1] is None:
                continue
            try:
                value = float(str(obs[1]).strip())
            except ValueError:
                continue
            pairs.append((period, value))
        if source_id:
            series_map[source_id] = pairs

    probabilities: dict[str, list[dict[str, Any]]] = {"final": [], "advance": []}
    for source_id, (release_type, label) in CHICAGO_PROBABILITY_BINS.items():
        pairs = series_map.get(source_id) or []
        if not pairs:
            continue
        period, value = sorted(pairs, key=lambda item: item[0])[-1]
        probabilities[release_type].append(
            {"bin": label, "period": period, "value": value, "source_id": source_id}
        )

    bundle = {
        "ok": True,
        "body": raw,
        "raw_sha256": _sha256(raw),
        "http_status": payload.get("http_status"),
        "source_url": json_url,
        "portal_url": CHICAGO_PORTAL_URL,
        "vintage": str(document.get("transmissionDt") or "latest_available"),
        "release_id": document.get("releaseID"),
        "release_date": release_date,
        "series": series_map,
        "probabilities": probabilities,
    }
    return cache_put(opener, "chicago_fed_lmi", bundle)


def _failed(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "status": bundle.get("status") or "source_failed",
        "error": bundle.get("error") or "chicago_fed_unavailable",
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
        "challenge_page": bundle.get("challenge_page"),
    }


def _decorate(points: list[dict[str, Any]], bundle: dict[str, Any], *, revision_status: str, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not points:
        return []
    latest_period = points[-1]["period"]
    decorated: list[dict[str, Any]] = []
    for point in points:
        row = {
            **point,
            "transformation": point.get("transformation"),
            "revision_status": revision_status,
            "source_url": bundle["source_url"],
            "vintage": bundle["vintage"],
        }
        if point["period"] == latest_period and bundle.get("release_date"):
            row["release_date"] = bundle["release_date"]
        derivation = {
            "publisher": "Federal Reserve Bank of Chicago",
            "portal_url": bundle["portal_url"],
            "release_id": bundle.get("release_id"),
            "vintage": bundle["vintage"],
        }
        if extra and point["period"] == latest_period:
            derivation.update(extra)
        row["derivation"] = derivation
        if row.get("transformation") is None:
            row.pop("transformation", None)
        decorated.append(row)
    return decorated


def fetch_chicago_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
) -> dict[str, Any]:
    bundle = load_chicago_bundle(opener, timeout=timeout)
    if not bundle.get("ok"):
        return _failed(bundle)

    catalog_id = str(spec["id"])
    series_map: dict[str, list[tuple[str, float]]] = bundle["series"]
    if catalog_id == "US.Labor.chicago_fed_nowcast_revision":
        final_pairs = {period: value for period, value in series_map.get(_FINAL_NOWCAST, [])}
        advance_pairs = {period: value for period, value in series_map.get(_ADVANCE_NOWCAST, [])}
        common = sorted(set(final_pairs) & set(advance_pairs))
        pairs = [(period, final_pairs[period] - advance_pairs[period]) for period in common]
        points = _points_from_pairs(pairs)
        for point in points:
            point["transformation"] = "percentage_points"
        extra = {"formula": "final_p50 - advance_p50"}
        revision_status = "final"
    else:
        source_id = CHICAGO_SERIES.get(catalog_id) or str(spec.get("series_id") or "")
        pairs = series_map.get(source_id) or []
        points = _points_from_pairs(pairs)
        if catalog_id == "US.Labor.chicago_fed_u3_nowcast_final":
            revision_status = "final"
            extra = {
                "probability_distribution": bundle["probabilities"].get("final") or [],
                "release_type": "final",
            }
        elif catalog_id == "US.Labor.chicago_fed_u3_nowcast_advance":
            revision_status = "advance"
            extra = {
                "probability_distribution": bundle["probabilities"].get("advance") or [],
                "release_type": "advance",
            }
        else:
            revision_status = "final"
            extra = None
        for point in points:
            point["transformation"] = "percent"

    if not points:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "chicago_fed_series_empty",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
        }
    return {
        "ok": True,
        "points": _decorate(points, bundle, revision_status=revision_status, extra=extra),
        "vintage": bundle["vintage"],
        "raw_sha256": bundle["raw_sha256"],
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
    }
