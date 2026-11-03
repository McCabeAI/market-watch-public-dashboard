"""Recover publisher release dates from archived raw evidence (offline)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scripts.macro_freshness import values_close
from scripts.macro_ingestion.us_employment.ism_prnewswire import parse_ism_pmi

ROOT = Path(__file__).resolve().parents[2]
LAUNCHES_RAW_ROOT = ROOT / "data/market_watch_launches"

_ISM_SERIES = frozenset({"NAPM", "NMFBAI"})


def _ism_services(series_id: str) -> bool:
    return series_id == "NMFBAI"


def release_date_from_raw_sha256(
    *,
    raw_sha256: str,
    period: str,
    value: float,
    series_id: str,
    launches_root: Path | None = None,
) -> str | None:
    """Match archived raw HTML by hash prefix and confirm period/value before trusting dates."""
    if series_id not in _ISM_SERIES:
        return None
    digest = str(raw_sha256 or "").strip().lower()
    if len(digest) < 12:
        return None
    prefix = digest[:12]
    root = launches_root or LAUNCHES_RAW_ROOT
    if not root.is_dir():
        return None
    services = _ism_services(series_id)
    candidates: list[Path] = []
    for path in root.glob("*/ingestion/raw/us/*/*"):
        if prefix not in path.name:
            continue
        candidates.append(path)
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            continue
        parsed = parse_ism_pmi(body, services=services)
        if not parsed:
            continue
        if str(parsed.get("period")) != period:
            continue
        try:
            parsed_value = float(parsed["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if not values_close(parsed_value, value):
            continue
        release_date = parsed.get("release_date")
        if isinstance(release_date, str) and release_date:
            return release_date[:10]
    return None


def enrich_points_release_dates(
    points: list[dict[str, Any]],
    *,
    launches_root: Path | None = None,
) -> None:
    for point in points:
        existing = point.get("release_date")
        if isinstance(existing, str) and existing.strip():
            continue
        raw_sha = point.get("raw_sha256")
        series_id = point.get("series_id")
        period = point.get("period")
        value = point.get("value")
        if not isinstance(raw_sha, str) or not isinstance(series_id, str):
            continue
        if not isinstance(period, str):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        recovered = release_date_from_raw_sha256(
            raw_sha256=raw_sha,
            period=period,
            value=numeric,
            series_id=series_id,
            launches_root=launches_root,
        )
        if recovered:
            point["release_date"] = recovered
